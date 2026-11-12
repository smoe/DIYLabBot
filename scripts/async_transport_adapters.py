"""Journal-independent T1 teleportation fixtures, not physical transport workers.

Only ``submit(envelope)`` is implemented. It returns detached messages for the
owner to persist individually; it never ingests them, changes inventory, waits,
or starts motion. The returned principals are synthetic fixture contexts, not
authenticated identities. A real adapter needs an external trust boundary.

The cache is local to this instance/boot. Construction does not recover or
redispatch anything. The owner must reconcile an uncertain dispatch rather than
submit it automatically to a new worker. There is no durable or physical
exactly-once promise, nor a query/event-stream/cancellation SPI yet.
"""
import copy
import uuid

import async_transport_domain as domain


class _TeleportMock:
    """Shared synthetic implementation; subclasses only select the agent kind."""

    kind = None

    def __init__(self, agent_id, *, order=None, boot_id=None):
        self.agent_id = domain.ident(agent_id)
        self.boot_id = domain.ident(uuid.uuid4().hex if boot_id is None else boot_id)
        roles = tuple(domain.load_contract()['roles'])
        selected = roles if order is None else order
        domain.require(isinstance(selected, (list, tuple))
                       and len(selected) == len(roles)
                       and all(isinstance(role, str) for role in selected)
                       and len(set(selected)) == len(roles)
                       and set(selected) == set(roles),
                       'Mock order must permute all four observation roles')
        self.order = tuple(selected)
        self._batches = {}

    def submit(self, envelope):
        """Return one worker claim and four explicit synthetic attestations.

        The envelope is validated and copied at entry. The caller may choose
        any receipt order, including delivery before pickup; the authoritative
        reducer, not the worker, decides when each receipt is causally applicable.
        Repeated identical submissions return copies of the same within-boot
        batch. Conflicting reuse of a run/job/epoch is rejected.
        """
        value = domain.decode_envelope(envelope)
        domain.require(value['agent_id'] == self.agent_id,
                       'Transport envelope is assigned to another agent')
        domain.require(value['agent_kind'] == self.kind,
                       'Transport envelope needs a different mock agent kind')
        fingerprint = domain.hashed(value)
        key = (value['run_id'], value['job_id'], value['assignment_epoch'])
        prior = self._batches.get(key)
        if prior is not None:
            domain.require(prior[0] == fingerprint,
                           'Transport assignment was already submitted with different arguments')
            return copy.deepcopy(prior[1])

        # A boot affects only the claim identity. Receipt identities bind the
        # complete immutable assignment and role and remain stable across boots.
        claim_id = 'mock_claim_' + domain.hashed({'envelope_sha256': fingerprint,
                                                 'boot_id': self.boot_id})
        claim = domain.claim_for(value, claim_id)
        batch = [{'principal': value['agent_principal'],
                  'request_id': 'request_' + claim_id,
                  'operation': 'worker_claim',
                  'args': {'job_id': value['job_id'], 'claim': claim}}]
        for role in self.order:
            observation_id = 'mock_observation_' + domain.hashed({
                'envelope_sha256': fingerprint, 'role': role})
            observation = domain.observation_for(value, role, observation_id)
            batch.append({'principal': domain.principal_for(value, role),
                          'request_id': 'request_' + observation_id,
                          'operation': 'observe',
                          'args': {'job_id': value['job_id'], 'observation': observation}})
        self._batches[key] = (fingerprint, copy.deepcopy(batch))
        return copy.deepcopy(batch)


class HumanTeleportMock(_TeleportMock):
    """Synthetic courier attestations, with zero travel time and no real courier."""

    kind = 'human'


class RobotTeleportMock(_TeleportMock):
    """Synthetic robot attestations, without geometry, trajectory, ROS or hardware."""

    kind = 'robot'
