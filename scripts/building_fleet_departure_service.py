"""Ordered successor reservations for source-authorized live depot departures."""
from types import MappingProxyType

from building_fleet_services import ResourceServices, finite


class DepartureResourceServices(ResourceServices):
    """Keep the exclusive token while a checked batch takes its queued turns."""

    def __init__(self, resources, waiting_places=None, maximum_queue=20):
        super().__init__(resources, waiting_places, maximum_queue)
        self._departure_successors = {}
        self._promoted_resources = set()
        self._departure_resources = frozenset()

    @property
    def departure_successors(self):
        """Dispatcher-only tuples in promotion order, without passage ownership."""
        return MappingProxyType(self._departure_successors)

    def enable_depot_departures(self, resource_ids):
        """Bind this session's source-derived depot resource IDs once."""
        resources=frozenset(resource_ids)
        if (not resources or any(self.resources.get(key) not in ('depot','room') for key in resources)
                or self._departure_resources and resources!=self._departure_resources):
            raise ValueError('Expected the same source-bound depot resources for this session')
        self._departure_resources=resources

    def reserve_departure_successor(self, vehicle, resource, leader, now):
        """Append a queued vehicle for a caller-checked depot departure.

        The existing owner keeps its token. Its release closes the batch.
        After all nominees take their turns, the ordinary FIFO head goes next.
        """
        finite(now)
        if (not all(isinstance(name,str) and name for name in (vehicle,resource,leader))
                or resource not in self._departure_resources
                or self.owners.get(resource)!=leader or vehicle==leader
                or self.holds.get(leader)!=resource or resource in self._promoted_resources):
            return False
        request=self.requests.get(vehicle)
        if request is None or request[0]!=resource or request[1]>now:
            return False
        if vehicle not in self.queues[resource]:
            return False
        batch = self._departure_successors.get(resource, ())
        if vehicle not in batch:
            self._departure_successors[resource] = (*batch, vehicle)
        return True

    def _grant(self, resource, now):
        if resource not in self.owners:
            batch = self._departure_successors.get(resource)
            if batch:
                nominee, *remaining = batch
                queue = self.queues[resource]
                queue.remove(nominee)
                queue.insert(0, nominee)
                self._promoted_resources.add(resource)
                if remaining:
                    self._departure_successors[resource] = tuple(remaining)
                else:
                    del self._departure_successors[resource]
            else:
                self._promoted_resources.discard(resource)
        super()._grant(resource, now)
