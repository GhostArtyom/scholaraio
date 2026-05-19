"""Compute the computational basis decomposition of a stabilizer state.

Supports two Pauli string formats:
- Positional:  "ZZXI"   (left = highest qubit, 0-based)
- Indexed:     "Z12X3"  (digit after operator = qubit index, 1-based)
"""


def _multiply(a: tuple[int, int, int], b: tuple[int, int, int]) -> tuple[int, int, int]:
    """Multiply two Pauli operators: a * b."""
    x_a, z_a, phi_a = a
    x_b, z_b, phi_b = b
    extra = 2 * ((z_a & x_b).bit_count() % 2)
    return (x_a ^ x_b, z_a ^ z_b, (phi_a + phi_b + extra) % 4)


def _apply(pauli: tuple[int, int, int], state: int) -> tuple[int, complex]:
    """Apply Pauli to a computational basis state. Returns (new_state, amplitude)."""
    x, z, phi = pauli
    new_state = state ^ x
    z_parity = (z & state).bit_count() % 2
    phase = 1j**phi
    if z_parity:
        phase = -phase
    return new_state, phase


def _is_indexed(label: str) -> bool:
    """Detect whether a Pauli string uses the index-based format."""
    return any(ch.isdigit() for ch in label)


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
    """Parse an index-based Pauli string. Returns (x_bits, z_bits, phi, n)."""
    stripped = label.lstrip("-")
    minus = len(label) - len(stripped)
    phi = (2 * minus) % 4
    max_q = 0
    x_bits = 0
    z_bits = 0
    current_char = ""
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


def stabilizer_state(generators: list[str]) -> list[str]:
    """Return the computational basis decomposition of the stabilizer codespace.

    Args:
        generators: Pauli strings in either positional ("ZZXI") or
                    indexed ("Z12X3") format. Optional '-' prefix for
                    -1 eigenspace.

    Returns:
        List of superposition ket strings.
    """
    if not generators:
        raise ValueError("at least one stabilizer generator required")

    parsed = [_parse_pauli(g) for g in generators]
    n = max(p[3] for p in parsed)
    paulis = [(x, z, phi) for x, z, phi, _ in parsed]

    group: list[tuple[int, int, int]] = [(0, 0, 0)]
    for p in paulis:
        new_elements: list[tuple[int, int, int]] = []
        for g in group:
            new_elements.append(_multiply(g, p))
        group.extend(new_elements)

    seen_supports: set[frozenset[int]] = set()
    result: list[str] = []

    for j in range(1 << n):
        amplitudes: dict[int, complex] = {}
        for g in group:
            s, amp = _apply(g, j)
            amplitudes[s] = amplitudes.get(s, 0j) + amp

        support = frozenset(s for s, a in amplitudes.items() if abs(a) > 1e-10)
        if not support or support in seen_supports:
            continue
        seen_supports.add(support)

        terms: list[str] = []
        for s in sorted(support):
            amp = amplitudes[s]
            if abs(amp.real) >= 1e-10:
                sign_val = 1 if amp.real > 0 else -1
            elif abs(amp.imag) >= 1e-10:
                sign_val = 1 if amp.imag > 0 else -1
            else:
                continue

            if not terms:
                if sign_val < 0:
                    terms.append(f"-|{s:0{n}b}⟩")
                else:
                    terms.append(f"|{s:0{n}b}⟩")
            else:
                terms.append(f"{'+ ' if sign_val > 0 else '- '}|{s:0{n}b}⟩")

        if terms:
            result.append(" ".join(terms))

    return result


if __name__ == "__main__":
    # GHZ stabilizer code
    generators = [
        "ZZI",
        "IZZ",
        "XXX",
    ]
    print(stabilizer_state(generators))

    # 5-qubit code
    generators = [
        "XZZXI",
        "IXZZX",
        "XIXZZ",
        "ZXIXZ",
    ]
    print(stabilizer_state(generators))

    # 7-qubit Steane code
    generators = [
        "ZZZZIII",
        "ZZIIZZI",
        "ZIZIZIZ",
        "XXXXIII",
        "XXIIXXI",
        "XIXIXIX",
    ]
    print(stabilizer_state(generators))

    # 9-qubit Shor code
    generators = [
        "ZZIIIIIII",
        "IZZIIIIII",
        "IIZZIIIII",
        "IIIZZIIII",
        "IIIIZZIII",
        "IIIIIZZII",
        "IIIIIIZZI",
        "IIIIIIIZZ",
        "XXXXXXXII",
        "IIXXXXXXX",
    ]
    print(stabilizer_state(generators))
