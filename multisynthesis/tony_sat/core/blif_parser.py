# tony_sat/core/blif_parser.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple


@dataclass
class NamesBlock:
    fanins: List[str]
    output: str
    cubes: List[str]  # e.g. "-0-0 1"


@dataclass
class BlifDesign:
    model: Optional[str]
    inputs: List[str]
    outputs: List[str]
    names: List[NamesBlock]


class BlifParseError(Exception):
    pass


def _strip_comment(line: str) -> str:
    if "#" in line:
        line = line.split("#", 1)[0]
    return line.strip()


def parse_blif(path: str) -> BlifDesign:
    """
    Parse a combinational LUT-mapped BLIF.
    Assumptions (as agreed):
      - only .model, .inputs, .outputs, .names, .end
      - no latches / clocks
      - LUTs have <= 4 fanins
    """
    model: Optional[str] = None
    inputs: List[str] = []
    outputs: List[str] = []
    names_blocks: List[NamesBlock] = []

    # current .names being parsed
    current_names: Optional[Tuple[List[str], str, List[str]]] = None
    # tuple = (fanins, output, cubes)

    def flush_current_names():
        nonlocal current_names
        if current_names is None:
            return
        fanins, out, cubes = current_names
        names_blocks.append(
            NamesBlock(fanins=list(fanins), output=out, cubes=list(cubes))
        )
        current_names = None

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = _strip_comment(raw)
            if not line:
                continue

            # Directive line
            if line.startswith("."):
                # IMPORTANT FIX:
                # Any directive closes a previous .names block,
                # INCLUDING a new .names
                flush_current_names()

                parts = line.split()
                directive = parts[0]

                if directive == ".model":
                    if len(parts) != 2:
                        raise BlifParseError(f"Invalid .model line: {line}")
                    model = parts[1]

                elif directive == ".inputs":
                    inputs.extend(parts[1:])

                elif directive == ".outputs":
                    outputs.extend(parts[1:])

                elif directive == ".names":
                    if len(parts) < 2:
                        raise BlifParseError(f"Invalid .names line: {line}")
                    *fanin_list, out = parts[1:]
                    current_names = (fanin_list, out, [])

                elif directive == ".end":
                    break

                else:
                    # Fail fast: thesis-proof, no hidden semantics
                    if directive in (".latch", ".clock", ".subckt", ".gate"):
                        raise BlifParseError(
                            f"Unsupported directive {directive} (expected combinational BLIF). "
                            f"Line: {line}"
                        )
                    raise BlifParseError(f"Unknown/unsupported directive: {line}")

            # Cube line
            else:
                if current_names is None:
                    raise BlifParseError(
                        f"Cube line outside of .names block: {line}"
                    )
                current_names[2].append(line)

    # Flush last open .names (if file ends without .end)
    flush_current_names()

    if not inputs:
        raise BlifParseError("No .inputs found in BLIF.")
    if not outputs:
        raise BlifParseError("No .outputs found in BLIF.")
    if not names_blocks:
        raise BlifParseError("No .names blocks found in BLIF.")

    return BlifDesign(
        model=model,
        inputs=inputs,
        outputs=outputs,
        names=names_blocks,
    )


def summarize(design: BlifDesign) -> Dict[str, int]:
    max_fanins = max((len(n.fanins) for n in design.names), default=0)
    return {
        "n_inputs": len(design.inputs),
        "n_outputs": len(design.outputs),
        "n_names": len(design.names),
        "max_fanins": max_fanins,
    }


if __name__ == "__main__":
    import argparse, json

    ap = argparse.ArgumentParser()
    ap.add_argument("--blif", required=True)
    args = ap.parse_args()

    d = parse_blif(args.blif)
    print(json.dumps(summarize(d), indent=2))

    for i, nb in enumerate(d.names[:5]):
        print(f"\n.names block {i}:")
        print("  fanins :", nb.fanins)
        print("  output :", nb.output)
        print("  cubes  :", len(nb.cubes))
        for c in nb.cubes[:5]:
            print("   ", c)
