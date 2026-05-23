"""Compute the computational basis decomposition of a stabilizer state.

Supports three Pauli string formats:
- Positional:        "ZZXI"          (left = highest qubit, 0-based)
- Indexed legacy:    "Z12X3"         (each digit = one qubit, 1-based)
- Indexed delimited: "Z1,2,X3,12" / "Z1 2 X3 12" (comma/space, multi-digit)
"""


def _multiply(a: tuple[int, int, int], b: tuple[int, int, int]) -> tuple[int, int, int]:
    """Multiply two Pauli operators: a * b."""
    x_a, z_a, phi_a = a
    x_b, z_b, phi_b = b
    extra = 2 * ((z_a & x_b).bit_count() % 2)
    return (x_a ^ x_b, z_a ^ z_b, (phi_a + phi_b + extra) % 4)


def _is_indexed(label: str) -> bool:
    """Detect whether a Pauli string uses the index-based format."""
    return "," in label or " " in label or any(ch.isdigit() for ch in label)


def _parse_positional(label: str) -> tuple[int, int, int, int]:
    """Parse a positional Pauli string. Returns (x_bits, z_bits, phi, n)."""
    stripped = label.lstrip("-")
    minus = len(label) - len(stripped)
    phi = (2 * minus) % 4
    n = len(stripped)
    x_bits = 0
    z_bits = 0
    for i, ch in enumerate(reversed(stripped)):
        if ch == "X":
            x_bits |= 1 << i
        elif ch == "Z":
            z_bits |= 1 << i
        elif ch == "Y":
            x_bits |= 1 << i
            z_bits |= 1 << i
            phi = (phi + 1) % 4
        elif ch != "I":
            raise ValueError(f"invalid Pauli character: {ch}")
    return x_bits, z_bits, phi, n


def _parse_indexed(label: str) -> tuple[int, int, int, int]:
    """Parse an index-based Pauli string. Returns (x_bits, z_bits, phi, n).

    Supports three sub-formats:
    - Legacy single-digit:  "X124"       (X on qubits 1, 2, 4)
    - Comma-separated:      "X5,7,8,11"  (X on qubits 5, 7, 8, 11)
    - Space-separated:      "X5 7 8 11"  (same, with spaces)
    """
    import re

    stripped = label.lstrip("-")
    minus = len(label) - len(stripped)
    phi = (2 * minus) % 4
    max_q = 0
    x_bits = 0
    z_bits = 0
    current_char = ""
    if "," in stripped or " " in stripped:
        for part in re.split(r"[\s,]+", stripped):
            if not part:
                continue
            if part[0] in "XYZI":
                current_char = part[0]
                num_str = part[1:]
            else:
                num_str = part
            if num_str:
                try:
                    q = int(num_str) - 1
                except ValueError:
                    raise ValueError(f"invalid qubit index in indexed format: {num_str}") from None
                max_q = max(max_q, q + 1)
                if current_char == "X":
                    x_bits |= 1 << q
                elif current_char == "Z":
                    z_bits |= 1 << q
                elif current_char == "Y":
                    x_bits |= 1 << q
                    z_bits |= 1 << q
                    phi = (phi + 1) % 4
                elif current_char == "I":
                    pass
                else:
                    raise ValueError(f"missing Pauli operator before qubit index {num_str}")
    else:
        # Legacy single-digit-per-character format
        for ch in stripped:
            if ch in "XYZI":
                current_char = ch
            elif ch.isdigit():
                q = int(ch) - 1
                max_q = max(max_q, q + 1)
                if current_char == "X":
                    x_bits |= 1 << q
                elif current_char == "Z":
                    z_bits |= 1 << q
                elif current_char == "Y":
                    x_bits |= 1 << q
                    z_bits |= 1 << q
                    phi = (phi + 1) % 4
            else:
                raise ValueError(f"invalid character in indexed format: {ch}")
    return x_bits, z_bits, phi, max_q


def _parse_pauli(label: str) -> tuple[int, int, int, int]:
    """Parse a Pauli string in either format. Returns (x, z, phi, n)."""
    if not label:
        raise ValueError("empty Pauli string")
    if _is_indexed(label.lstrip("-")):
        return _parse_indexed(label)
    return _parse_positional(label)


def to_indexed(generators: list[str]) -> list[str]:
    """Convert positional-format generators to indexed format."""
    result = []
    for g in generators:
        sign = "-" if g.startswith("-") else ""
        label = g.lstrip("-")
        groups: dict[str, list[str]] = {}
        for i, ch in enumerate(reversed(label)):
            q = i + 1
            if ch != "I":
                groups.setdefault(ch, []).append(str(q))
        indexed = sign
        for pauli in "XYZI":
            if pauli in groups:
                indexed += pauli + "".join(groups[pauli])
        result.append(indexed)
    return result


def to_positional(generators: list[str]) -> list[str]:
    """Convert indexed-format generators to positional format."""
    n = 0
    parsed: list[tuple[str, int, int]] = []
    for g in generators:
        sign = "-" if g.startswith("-") else "+"
        x_bits, z_bits, _phi, gn = _parse_indexed(g)
        n = max(n, gn)
        parsed.append((sign, x_bits, z_bits))
    result = []
    for sign, x, z in parsed:
        chars = []
        for q in range(n - 1, -1, -1):
            has_x = (x >> q) & 1
            has_z = (z >> q) & 1
            if has_x and has_z:
                chars.append("Y")
            elif has_x:
                chars.append("X")
            elif has_z:
                chars.append("Z")
            else:
                chars.append("I")
        prefix = "-" if sign == "-" else ""
        result.append(prefix + "".join(chars))
    return result


def _gf2_eliminate(rows: list[int], n: int) -> tuple[int, list[int], list[int]]:
    """Gaussian elimination over GF(2) on k rows of n-bit integers.

    Returns (rank, pivot_cols, reduced_rows).
    reduced_rows[:rank] are the pivot rows in row-echelon form; rows beyond rank
    are zero.
    """
    k = len(rows)
    row_list = list(rows)
    pivot_cols: list[int] = []
    pivot_row = 0

    for col in range(n):
        found = None
        for r in range(pivot_row, k):
            if (row_list[r] >> col) & 1:
                found = r
                break
        if found is None:
            continue
        row_list[pivot_row], row_list[found] = row_list[found], row_list[pivot_row]
        pivot_cols.append(col)

        row_p = row_list[pivot_row]
        for r in range(k):
            if r != pivot_row and ((row_list[r] >> col) & 1):
                row_list[r] ^= row_p
        pivot_row += 1

    return len(pivot_cols), pivot_cols, row_list


def _gf2_nullspace(rows: list[int], n: int) -> list[int]:
    """Basis for the nullspace of the k x n matrix over GF(2).

    Returns n - rank row vectors (as n-bit ints) spanning {v : rows·v = 0}.
    """
    if not rows:
        return [1 << i for i in range(n)]
    pivot_cols, reduced = _gf2_eliminate(rows, n)[1:]
    pivot_set = set(pivot_cols)
    nullspace: list[int] = []
    for col in range(n):
        if col in pivot_set:
            continue
        vec = 1 << col
        for p_idx, p_col in enumerate(pivot_cols):
            if (reduced[p_idx] >> col) & 1:
                vec |= 1 << p_col
        nullspace.append(vec)
    return nullspace


def _gf2_span_basis(vectors: list[int], n: int) -> list[int]:
    """Extract a linearly independent subset spanning the same subspace."""
    if not vectors:
        return []
    rank, reduced = _gf2_eliminate(vectors, n)[0::2]
    return [v for v in reduced[:rank] if v != 0]


def _find_logical_operators(
    generators: list[tuple[int, int, int]],
    group: list[tuple[int, int, int]],
    n: int,
    block: str,
) -> list[int]:
    """Find n-k independent logical operators, pure-X (block="X") or pure-Z (block="Z")."""
    # Constraint: (v,0) commutes with (x_s,z_s) iff v·z_s = 0 (X case)
    #             (0,v) commutes with (x_s,z_s) iff x_s·v = 0 (Z case)
    if block == "X":
        constraint_block = [z for _x, z, _phi in generators]
        pure_comps = [x for x, z, _phi in group if z == 0]
    else:
        constraint_block = [x for x, _z, _phi in generators]
        pure_comps = [z for x, z, _phi in group if x == 0]

    nullspace = _gf2_nullspace(constraint_block, n)
    pure_basis = _gf2_span_basis(pure_comps, n)

    if not pure_basis:
        return nullspace

    s_rank, s_pivots, s_reduced = _gf2_eliminate(pure_basis, n)

    operators: list[int] = []
    for v in nullspace:
        r = v
        for p_col, s_row in zip(s_pivots, s_reduced[:s_rank]):
            if (r >> p_col) & 1:
                r ^= s_row
        if r != 0:
            operators.append(r)

    return operators


def _build_logical_zero(group: list[tuple[int, int, int]]) -> dict[int, complex]:
    """Build P|0⟩ = Σ_{g∈S} g|0⟩ as {basis_state: amplitude}."""
    amps: dict[int, complex] = {}
    for x, _z, phi in group:
        amp = 1j**phi
        amps[x] = amps.get(x, 0j) + amp
    return amps


def _format_state(amplitudes: dict[int, complex], n: int) -> str:
    """Format a superposition dict as a ket string."""
    terms: list[str] = []
    for s in sorted(amplitudes):
        amp = amplitudes[s]
        if abs(amp) < 1e-10:
            continue
        if abs(amp.real) >= 1e-10:
            sign_val = 1 if amp.real > 0 else -1
        else:
            sign_val = 1 if amp.imag > 0 else -1

        if not terms:
            prefix = "-" if sign_val < 0 else ""
            terms.append(f"{prefix}|{s:0{n}b}⟩")
        else:
            terms.append(f"{'+ ' if sign_val > 0 else '- '}|{s:0{n}b}⟩")
    return " ".join(terms) if terms else ""


def stabilizer_state(generators: list[str]) -> list[str]:
    """Return the computational basis decomposition of the stabilizer codespace.

    Uses the stabilizer tableau method: O(2^n) instead of O(2^(n+k)).

    Args:
        generators: Pauli strings in positional, legacy-indexed, or
                    delimited-indexed format. Optional '-' prefix for
                    -1 eigenspace.

    Returns:
        List of superposition ket strings, one per logical basis state.
    """
    if not generators:
        raise ValueError("at least one stabilizer generator required")

    parsed = [_parse_pauli(g) for g in generators]
    n = max(p[3] for p in parsed)
    paulis = [(x, z, phi) for x, z, phi, _ in parsed]
    k = len(paulis)

    # 1. Generate stabilizer group (2^k elements)
    group: list[tuple[int, int, int]] = [(0, 0, 0)]
    for p in paulis:
        new_elements: list[tuple[int, int, int]] = []
        for g in group:
            new_elements.append(_multiply(g, p))
        group.extend(new_elements)

    n_logical = n - k

    if n_logical == 0:
        amps = _build_logical_zero(group)
        return [_format_state(amps, n)]

    # 2. Find logical X operators (pure-X, from Z-block nullspace)
    logical_xs = _find_logical_operators(paulis, group, n, "X")

    # 3. Build P|0⟩
    zero_amps = _build_logical_zero(group)

    # 4. Generate all 2^m logical basis states
    m = 1 << n_logical
    result: list[str] = []
    for j in range(m):
        x_comb = 0
        for bit in range(n_logical):
            if (j >> bit) & 1:
                x_comb ^= logical_xs[bit]

        if x_comb == 0:
            amps = dict(zero_amps)
        else:
            amps = {}
            for s, amp in zero_amps.items():
                amps[s ^ x_comb] = amps.get(s ^ x_comb, 0j) + amp

        result.append(_format_state(amps, n))

    return result


if __name__ == "__main__":
    stabilizer_code = {
        "GHZ code": [
            "ZZI",
            "IZZ",
            "XXX",
        ],
        "Steane code": [
            "IIIXXXX",
            "IXXIIXX",
            "XIXIXIX",
            "IIIZZZZ",
            "IZZIIZZ",
            "ZIZIZIZ",
        ],
        "Shor code": [
            "ZZIIIIIII",
            "IZZIIIIII",
            "IIIZZIIII",
            "IIIIZZIII",
            "IIIIIIZZI",
            "IIIIIIIZZ",
            "XXXXXXIII",
            "IIIXXXXXX",
        ]
    }
    for name, generators in stabilizer_code.items():
        states = stabilizer_state(generators)
        print(f"{name}: {len(states)} states")
        for state in states:
            print(f"  {state}")

    # Surface code
    generators = [
        "X1 2 4",
        "X2 3 5",
        "X4 6 7 9",
        "X5 7 8 10",
        "X9 11 12 14",
        "X10 12 13 15",
        "X14 16 17 19",
        "X15 17 18 20",
        "Z1 4 6",
        "Z2 4 5 7",
        "Z3 5 8",
        "Z6 9 11",
        "Z7 9 10 12",
        "Z8 10 13",
        "Z11 14 16",
        # "Z12 14 15 17",
        "Z13 15 18",
        "Z16 19",
        "Z17 19 20",
        "Z18 20",
    ]
    states = stabilizer_state(generators)
    print(f"Surface code: {len(states)} states")
