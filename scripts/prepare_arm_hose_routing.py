"""Prepare source-only fixed-material hose evidence without changing the model."""
import argparse
import json
from pathlib import Path

import arm_syringe as model


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        default=model.ROOT/'exports/arm-close-hose/routing-proof.json')
    args = parser.parse_args(argv)
    output = (args.output if args.output.is_absolute() else model.ROOT/args.output).resolve()
    if output == model.SOURCE.resolve():
        parser.error('The evidence output cannot overwrite the construction source')
    source_before = model.digest(model.SOURCE)
    spec = model.load()
    if 'hose_routing' not in spec:
        parser.error('This entry point requires the link-clipped hose recipe')
    proof = model.named_length_band(spec, model.parameters(spec))
    if model.digest(model.SOURCE) != source_before:
        raise ValueError('The construction source changed during routing preparation')
    protected = {(model.ROOT/name).resolve() for name in proof.get('source_files_sha256', {})}
    if output in protected:
        parser.error('The evidence output cannot overwrite a pinned construction dependency')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(proof, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({'passed': proof.get('passed') is True,
        'selected_cut_mm': proof.get('hose_length_mm'), 'named_states': len(proof.get('states', {})),
        'output': str(output)}), flush=True)
    return 0 if proof.get('passed') is True else 1


if __name__ == '__main__':
    raise SystemExit(main())
