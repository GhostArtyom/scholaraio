"""
QCCD QEC 编译器简化仿真：不同 trap 容量下的穿梭和门操作时间计算。
用 distance-2 rotated surface code（7 个物理 qubit）做具体例子。

用法: uv run code/qccd/qccd_time_sim.py
"""

from dataclasses import dataclass

# ============================================================
# QCCD 操作时序（来自 Table 1）
# ============================================================
T_GATE = 40       # MS 门（双量子比特门）
T_SPLIT = 80      # 分裂：离子从 trap 移入传输段
T_MERGE = 80      # 合并：离子从传输段移入 trap
T_SEG = 5         # 穿梭：离子沿传输段移动一格
T_JUNCTION = 100  # junction 进入或离开（单向）

# ============================================================
# Grid 拓扑：3x3 网格，支持最多 9 个 trap
# ============================================================
# 节点坐标 (x, y)
GRID_NODES = [(x, y) for x in range(3) for y in range(3)]

# 边：相邻节点自动连接（水平或垂直，曼哈顿距离 = 1）
GRID_EDGES = []
for (x1, y1) in GRID_NODES:
    for (x2, y2) in GRID_NODES:
        if abs(x1 - x2) + abs(y1 - y2) == 1 and (x1, y1) < (x2, y2):
            GRID_EDGES.append(((x1, y1), (x2, y2), False))


def neighbors(a, b):
    """判断两个节点是否直接相邻（1 段距离）"""
    return (abs(a[0] - b[0]) + abs(a[1] - b[1])) == 1


def shortest_path(src, dst):
    """计算从 src 到 dst 的最短路径（BFS），返回路径节点列表"""
    if src == dst:
        return [src]
    from collections import deque
    adj = {n: [] for n in GRID_NODES}
    for a, b, _ in GRID_EDGES:
        adj[a].append(b)
        adj[b].append(a)
    visited = {src}
    queue = deque([(src, [src])])
    while queue:
        node, path = queue.popleft()
        for nb in adj[node]:
            if nb == dst:
                return [*path, nb]
            if nb not in visited:
                visited.add(nb)
                queue.append((nb, [*path, nb]))
    return [src, dst]  # fallback


def snap_to_grid(pos):
    """将浮点坐标对齐到最近的 Grid 节点"""
    return (round(pos[0]), round(pos[1]))


def route_cost(src, dst):
    """
    计算从 src trap 到 dst trap 做一次 CNOT 的总时间。
    返回 (总时间, 路由时间, 是否需要穿梭)。
    """
    # 同位置 = 同 trap，无需穿梭
    if abs(src[0] - dst[0]) < 0.01 and abs(src[1] - dst[1]) < 0.01:
        return T_GATE, 0, False

    # 对齐到 Grid 节点做最短路径
    src_grid = snap_to_grid(src)
    dst_grid = snap_to_grid(dst)

    if src_grid == dst_grid:
        # 对齐后同节点 → 距离很近，算 1 段
        return T_GATE + T_SPLIT + T_SEG + T_MERGE, T_SPLIT + T_SEG + T_MERGE, True

    path = shortest_path(src_grid, dst_grid)
    n_segments = len(path) - 1

    # 判断是否经过 junction（路径拐弯 = 方向改变 = 需要过 junction）
    has_junction = False
    if n_segments >= 2:
        for i in range(len(path) - 2):
            dx1 = path[i + 1][0] - path[i][0]
            dy1 = path[i + 1][1] - path[i][1]
            dx2 = path[i + 2][0] - path[i + 1][0]
            dy2 = path[i + 2][1] - path[i + 1][1]
            if (dx1, dy1) != (dx2, dy2):
                has_junction = True
                break

    route = T_SPLIT + n_segments * T_SEG + T_MERGE
    if has_junction:
        route += 2 * T_JUNCTION  # entry + exit

    total = route + T_GATE
    return total, route, True


# ============================================================
# Surface Code 定义：distance-2 rotated surface code
# ============================================================
# Surface Code 的 qubit 在 Grid 上的物理位置
# d=2 rotated surface code：data qubit 在角落，ancilla 在中间
#   D1(0,0) ── A1(1,0) ── D2(2,0)
#     |           |           |
#   A3(0,1) ── D4(1,1) ── A2(2,1)
#                             |
#                       D3(2,2)
QUBIT_POS = {
    'D1': (0, 0),
    'A1': (1, 0),
    'D2': (2, 0),
    'A3': (0, 1),
    'D4': (1, 1),
    'A2': (2, 1),
    'D3': (2, 2),
}

# 每个 ancilla 的校验目标（CNOT 顺序）
ANCILLA_CNOTS = {
    'A1': ['D1', 'D2', 'D4'],
    'A2': ['D2', 'D3', 'D4'],
    'A3': ['D3', 'D4'],
}


@dataclass
class TrapAssignment:
    """trap 分配方案"""
    name: str
    # qubit -> trap_id 的映射
    qubit_to_trap: dict
    # trap_id -> set of qubits
    trap_contents: dict
    # trap_id -> 物理坐标 (x, y)
    trap_positions: dict


def make_assignment_C2():
    """C=2：每个 qubit 独占一个 trap（7 个 trap，每个 1 个 qubit）"""
    q2t = {}
    tc = {}
    tp = {}
    for name, pos in QUBIT_POS.items():
        trap_id = f"T_{name}"
        q2t[name] = trap_id
        tc[trap_id] = {name}
        tp[trap_id] = pos
    return TrapAssignment("C=2", q2t, tc, tp)


def make_assignment_C3():
    """C=3：递归二分分区 → 4 个 trap（C-1=2，ceil(7/2)=4）"""
    # 递归二分 surface code 网格：
    # 第 1 步：纵向切中间 (x=1) → 左 {(0,0),(0,1)} 右 {(1,0),(1,1),(2,0),(2,1),(2,2)}
    # 第 2 步：左半横向切 → {(0,0)} {(0,1)}
    #          右半横向切 → {(1,0),(1,1)} {(2,0),(2,1),(2,2)}
    # 结果：4 个 cluster
    q2t = {
        'D1': 'T0', 'A3': 'T0',         # (0,0), (0,1) → 左上
        'A1': 'T1',                       # (1,0) → 中上
        'D4': 'T2',                       # (1,1) → 中心
        'D2': 'T3', 'A2': 'T3', 'D3': 'T3',  # (2,0),(2,1),(2,2) → 右侧
    }
    tc = {
        'T0': {'D1', 'A3'},
        'T1': {'A1'},
        'T2': {'D4'},
        'T3': {'D2', 'A2', 'D3'},
    }
    # trap 位置 = cluster 中所有 qubit 位置的质心
    def centroid(qubits):
        positions = [QUBIT_POS[q] for q in qubits]
        return (sum(p[0] for p in positions) / len(positions),
                sum(p[1] for p in positions) / len(positions))
    tp = {tid: centroid(qs) for tid, qs in tc.items()}
    return TrapAssignment("C=3", q2t, tc, tp)


def make_assignment_C4():
    """C=4：3 个 trap（C-1=3，ceil(7/3)=3）"""
    # 递归二分：先纵向切 → 左 {(0,0),(0,1)} 右 {(1,0),(1,1),(2,0),(2,1),(2,2)}
    # 左半不动（2 个 qubit ≤ 3），右半横向切 → {(1,0),(1,1)} {(2,0),(2,1),(2,2)}
    q2t = {
        'D1': 'T0', 'A3': 'T0',              # 左侧
        'A1': 'T1', 'D4': 'T1',               # 中部
        'D2': 'T2', 'A2': 'T2', 'D3': 'T2',  # 右侧
    }
    tc = {
        'T0': {'D1', 'A3'},
        'T1': {'A1', 'D4'},
        'T2': {'D2', 'A2', 'D3'},
    }
    def centroid(qubits):
        positions = [QUBIT_POS[q] for q in qubits]
        return (sum(p[0] for p in positions) / len(positions),
                sum(p[1] for p in positions) / len(positions))
    tp = {tid: centroid(qs) for tid, qs in tc.items()}
    return TrapAssignment("C=4", q2t, tc, tp)


def simulate(assignment: TrapAssignment):
    """
    简化仿真：计算一轮 syndrome extraction 的 elapsed time。

    模型：
    - 每个 ancilla 按顺序执行其 CNOT 列表
    - 同 trap 内的门串行执行（维护 trap 时间线）
    - 不同 trap 的门可并行
    - 路由（穿梭）发生在目标 trap，占用目标 trap 的时间
    """
    # 每个 trap 的时间线（下一个可用时间）
    trap_timeline = {tid: 0.0 for tid in assignment.trap_contents}

    total_gate_time = 0.0
    total_route_time = 0.0
    op_details = []

    for ancilla, targets in ANCILLA_CNOTS.items():
        ancilla_trap = assignment.qubit_to_trap[ancilla]
        current_pos = assignment.trap_positions[ancilla_trap]

        for target in targets:
            target_trap = assignment.qubit_to_trap[target]
            target_pos = assignment.trap_positions[target_trap]

            # 计算路由代价
            total_cost, route_cost_val, needs_shuttle = route_cost(
                current_pos, target_pos
            )

            # 确定门在哪个 trap 执行
            if needs_shuttle:
                exec_trap = target_trap
            else:
                exec_trap = ancilla_trap

            # 门可以开始的最早时间 = max(ancilla 上一步完成, 目标 trap 空闲)
            # 简化：ancilla 串行执行，所以门开始时间 = max(当前时间, trap 空闲时间)
            gate_start = max(trap_timeline.get(ancilla_trap, 0),
                             trap_timeline.get(exec_trap, 0))
            gate_end = gate_start + total_cost

            # 更新 trap 时间线
            if needs_shuttle:
                # 路由期间：源 trap 被占用（split），目标 trap 被占用（merge + gate）
                # 简化：整个操作占用执行 trap
                trap_timeline[exec_trap] = gate_end
                # ancilla 回到原位的代价（简化：不计回程）
                trap_timeline[ancilla_trap] = gate_start + T_SPLIT  # split 后源 trap 空闲
            else:
                trap_timeline[exec_trap] = gate_end

            total_gate_time += T_GATE
            total_route_time += route_cost_val

            op_details.append({
                'ancilla': ancilla,
                'target': target,
                'from': current_pos,
                'to': target_pos,
                'exec_trap': exec_trap,
                'gate_start': gate_start,
                'gate_end': gate_end,
                'total_cost': total_cost,
                'route_cost': route_cost_val,
                'needs_shuttle': needs_shuttle,
            })

            # 更新 ancilla 当前位置
            if needs_shuttle:
                current_pos = target_pos

    # elapsed time = 所有 trap 时间线的最大值
    elapsed = max(trap_timeline.values())
    n_local = sum(1 for d in op_details if not d['needs_shuttle'])
    n_remote = sum(1 for d in op_details if d['needs_shuttle'])
    n_junction = sum(1 for d in op_details
                     if d['needs_shuttle'] and d['route_cost'] > 250)

    return {
        'elapsed': elapsed,
        'total_gate': total_gate_time,
        'total_route': total_route_time,
        'n_local': n_local,
        'n_remote': n_remote,
        'n_junction': n_junction,
        'n_ops': len(op_details),
        'details': op_details,
        'trap_timeline': dict(trap_timeline),
    }


def print_result(name, result, assignment):
    """打印仿真结果"""
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")

    # Trap 分配
    print(f"\n  Trap 分配（C={name.split('=')[1]}）：")
    for tid in sorted(assignment.trap_contents):
        pos = assignment.trap_positions[tid]
        qubits = ', '.join(sorted(assignment.trap_contents[tid]))
        print(f"    {tid} @ {pos}: {{{qubits}}}")

    # 操作详情
    print("\n  操作详情：")
    print(f"  {'Anc':>3} {'Target':>6} {'From':>6} {'To':>6} "
          f"{'ExecTrap':>8} {'Cost':>6} {'Route':>6} {'Shuttle':>7}")
    print(f"  {'-'*3} {'-'*6} {'-'*6} {'-'*6} {'-'*8} {'-'*6} {'-'*6} {'-'*7}")
    for d in result['details']:
        shuttle_str = "YES" if d['needs_shuttle'] else "no"
        print(f"  {d['ancilla']:>3} {d['target']:>6} "
              f"{d['from']!s:>6} {d['to']!s:>6} "
              f"{d['exec_trap']:>8} {d['total_cost']:>6.0f} "
              f"{d['route_cost']:>6.0f} {shuttle_str:>7}")

    # Trap 时间线
    print("\n  Trap 时间线（完成时间 μs）：")
    for tid in sorted(result['trap_timeline']):
        print(f"    {tid}: {result['trap_timeline'][tid]:.0f} μs")

    # 汇总
    print("\n  汇总：")
    print(f"    总 elapsed time:  {result['elapsed']:.0f} μs")
    print(f"    门操作时间（总计）: {result['total_gate']:.0f} μs")
    print(f"    路由时间（关键路径）: {max(0, result['elapsed'] - result['total_gate']):.0f} μs")
    print(f"    本地门: {result['n_local']}/{result['n_ops']}，"
          f"需穿梭: {result['n_remote']}/{result['n_ops']}，"
          f"过 junction: {result['n_junction']}/{result['n_ops']}")
    print(f"    Trap 数: {len(assignment.trap_contents)}")


def print_comparison(results):
    """打印对比表"""
    print(f"\n{'='*60}")
    print("  汇总对比")
    print(f"{'='*60}")

    header = f"  {'':>8} {'C=2':>10} {'C=3':>10} {'C=4':>10}"
    print(header)
    print(f"  {'-'*8} {'-'*10} {'-'*10} {'-'*10}")

    keys = [
        ('Elapsed(μs)', 'elapsed'),
        ('Gate(μs)', 'total_gate'),
        ('Route(μs)', lambda r: max(0, r['elapsed'] - r['total_gate'])),
        ('Traps', lambda r: len(r['trap_timeline'])),
        ('Local%', lambda r: f"{r['n_local']/r['n_ops']*100:.0f}%"),
        ('Remote%', lambda r: f"{r['n_remote']/r['n_ops']*100:.0f}%"),
    ]

    names = list(results.keys())
    for label, key in keys:
        vals = []
        for name in names:
            r = results[name]
            if callable(key):
                v = key(r)
            else:
                v = r[key]
            if isinstance(v, float):
                vals.append(f"{v:>10.0f}")
            else:
                vals.append(f"{v!s:>10}")
        print(f"  {label:>8} {''.join(vals)}")


def main():
    assignments = {
        'C=2': make_assignment_C2(),
        'C=3': make_assignment_C3(),
        'C=4': make_assignment_C4(),
    }

    results = {}
    for name, assignment in assignments.items():
        result = simulate(assignment)
        results[name] = result
        print_result(name, result, assignment)

    print_comparison(results)

    # 验证：打印单次路由代价表
    print(f"\n{'='*60}")
    print("  单次路由代价表（μs）")
    print(f"{'='*60}")
    print(f"  {'Src':>6} -> {'Dst':>6} {'Seg':>4} {'Jct':>4} "
          f"{'Route':>6} {'Gate':>6} {'Total':>6}")
    for src in GRID_NODES:
        for dst in GRID_NODES:
            total, route, needs = route_cost(src, dst)
            path = shortest_path(src, dst)
            n_seg = len(path) - 1
            has_jct = "yes" if route > 250 else "no"
            if not needs:
                print(f"  {src!s:>6} -> {dst!s:>6} {0:>4} {'--':>4} "
                      f"{0:>6} {T_GATE:>6} {total:>6.0f}")
            else:
                print(f"  {src!s:>6} -> {dst!s:>6} {n_seg:>4} {has_jct:>4} "
                      f"{route:>6} {T_GATE:>6} {total:>6.0f}")


if __name__ == '__main__':
    main()
