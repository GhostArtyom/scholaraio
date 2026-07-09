"""
QCCD Routing 可视化：为 C=2, C=3, C=4 三种 trap 容量画出 qubit 分布、路由路径和时间线。
输出 PNG 图片到 workspace/trapped-ion/figures/qccd/ 目录。

用法: uv run code/qccd/qccd_visualize.py
"""

import os

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch

# 输出目录（相对于脚本位置）
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figures")
os.makedirs(OUT_DIR, exist_ok=True)

# 颜色
C_DATA = '#4A90D9'       # data qubit - 蓝
C_ANCILLA = '#E74C3C'    # ancilla - 红
C_TRAP = '#2C3E50'       # trap 边框 - 深灰
C_TRAP_FILL = '#ECF0F1'  # trap 填充 - 浅灰
C_ROUTE = '#E67E22'      # 路由路径 - 橙
C_GATE = '#27AE60'       # 门操作 - 绿
C_JUNCTION = '#F39C12'   # junction - 黄

# qubit 物理位置 (x, y) 在 3x3 Grid 上
QUBIT_POS = {
    'D1': (0, 2), 'A1': (1, 2), 'D2': (2, 2),
    'A3': (0, 1), 'D4': (1, 1), 'A2': (2, 1),
    'D3': (2, 0),
}

# ancilla 校验目标
ANCILLA_CNOTS = {
    'A1': ['D1', 'D2', 'D4'],
    'A2': ['D2', 'D3', 'D4'],
    'A3': ['D3', 'D4'],
}

# C=2 trap 分配：每个 qubit 独占一个 trap
ASSIGN_C2 = {q: q for q in QUBIT_POS}

# C=3 trap 分配（4 个 trap，C-1=2）
ASSIGN_C3 = {
    'D1': 'T0', 'A3': 'T0',
    'A1': 'T1',
    'D4': 'T2',
    'D2': 'T3', 'A2': 'T3', 'D3': 'T3',
}

# C=4 trap 分配（3 个 trap，C-1=3）
ASSIGN_C4 = {
    'D1': 'T0', 'A3': 'T0',
    'A1': 'T1', 'D4': 'T1',
    'D2': 'T2', 'A2': 'T2', 'D3': 'T2',
}

def trap_centroids(assignment):
    """计算每个 trap 的质心位置"""
    trap_qubits = {}
    for q, t in assignment.items():
        trap_qubits.setdefault(t, []).append(q)
    centroids = {}
    for t, qs in trap_qubits.items():
        xs = [QUBIT_POS[q][0] for q in qs]
        ys = [QUBIT_POS[q][1] for q in qs]
        centroids[t] = (np.mean(xs), np.mean(ys))
    return centroids, trap_qubits

def draw_grid(ax, title):
    """画 Grid 背景（3x3 节点 + 边）"""
    ax.set_xlim(-0.5, 2.5)
    ax.set_ylim(-0.5, 2.5)
    ax.set_aspect('equal')
    ax.set_title(title, fontsize=14, fontweight='bold', pad=12)
    ax.set_xticks([0, 1, 2])
    ax.set_yticks([0, 1, 2])
    ax.grid(True, alpha=0.2, linestyle='--')

    # 画边
    for x in range(3):
        for y in range(3):
            if x < 2:
                ax.plot([x, x+1], [y, y], 'k-', alpha=0.15, linewidth=1)
            if y < 2:
                ax.plot([x, x], [y, y+1], 'k-', alpha=0.15, linewidth=1)

    # junction 节点标记（中心节点）
    ax.plot(1, 1, 's', color=C_JUNCTION, markersize=15, alpha=0.3, zorder=1)
    ax.text(1, 1, 'J', ha='center', va='center', fontsize=8, color='#7F8C8D', zorder=2)

def draw_traps(ax, assignment, show_bounding_box=True):
    """画 trap 边界和 qubit"""
    centroids, trap_qubits = trap_centroids(assignment)

    # 按 trap 分组画边界框（用不同颜色区分）
    trap_colors = ['#3498DB', '#E74C3C', '#2ECC71', '#F39C12', '#9B59B6', '#1ABC9C']
    trap_list = sorted(trap_qubits.keys())

    if show_bounding_box:
        for i, t in enumerate(trap_list):
            qs = trap_qubits[t]
            xs = [QUBIT_POS[q][0] for q in qs]
            ys = [QUBIT_POS[q][1] for q in qs]
            margin = 0.35
            color = trap_colors[i % len(trap_colors)]
            rect = mpatches.FancyBboxPatch(
                (min(xs) - margin, min(ys) - margin),
                max(xs) - min(xs) + 2*margin,
                max(ys) - min(ys) + 2*margin,
                boxstyle="round,pad=0.05",
                facecolor=color,
                edgecolor=color,
                linewidth=2.5,
                alpha=0.15,
                zorder=1,
            )
            ax.add_patch(rect)
            # trap 标签（在边界框内左上角）
            # cx, cy = centroids[t]
            label = f"{t}: {','.join(sorted(qs))}"
            ax.text(min(xs) - margin + 0.05, max(ys) + margin - 0.05, label,
                    ha='left', va='top', fontsize=6.5, color=color,
                    fontweight='bold', zorder=3,
                    bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.8, edgecolor=color, linewidth=0.5))

    # 画 qubit（在边界框之上）
    for q, (x, y) in QUBIT_POS.items():
        color = C_ANCILLA if q.startswith('A') else C_DATA
        circle = plt.Circle((x, y), 0.2, color=color, zorder=4,
                           edgecolor='white', linewidth=1.5)
        ax.add_patch(circle)
        ax.text(x, y, q, ha='center', va='center',
                fontsize=8, fontweight='bold', color='white', zorder=5)

def draw_routes(ax, assignment, routes):
    """画路由路径（箭头）"""
    centroids, _ = trap_centroids(assignment)

    for src_q, dst_q in routes:
        src_trap = assignment[src_q]
        dst_trap = assignment[dst_q]
        if src_trap == dst_trap:
            continue  # 同 trap 不画

        # sx, sy = QUBIT_POS[src_q]
        # dx, dy = QUBIT_POS[dst_q]

        # 用 trap 质心画路径（更清晰）
        sx_c, sy_c = centroids[src_trap]
        dx_c, dy_c = centroids[dst_trap]

        # 路线经过的节点
        # mid_x, mid_y = (sx_c + dx_c) / 2, (sy_c + dy_c) / 2

        arrow = FancyArrowPatch(
            (sx_c, sy_c), (dx_c, dy_c),
            arrowstyle='->,head_width=0.15,head_length=0.1',
            color=C_ROUTE,
            linewidth=2,
            alpha=0.7,
            zorder=3,
            connectionstyle="arc3,rad=0.1",
        )
        ax.add_patch(arrow)

def draw_timeline(ax, assignment, cnot_sequence, title):
    """画执行时间线（甘特图）"""
    _, trap_qubits = trap_centroids(assignment)
    trap_list = sorted(trap_qubits.keys())
    trap_idx = {t: i for i, t in enumerate(trap_list)}

    # 时序参数
    T_GATE = 40
    T_ROUTE_SHORT = 205   # 1 段无 junction
    # T_ROUTE_LONG = 410    # 2 段过 junction

    # 简化调度：按 ancilla 顺序执行，记录每个 trap 的时间线
    trap_timeline = {t: [] for t in trap_list}
    current_time = {t: 0 for t in trap_list}

    for ancilla, target in cnot_sequence:
        src_trap = assignment[ancilla]
        dst_trap = assignment[target]

        if src_trap == dst_trap:
            t_start = current_time[src_trap]
            t_end = t_start + T_GATE
            trap_timeline[src_trap].append((t_start, t_end, f'{ancilla}→{target}', 'gate'))
            current_time[src_trap] = t_end
        else:
            # 路由 + 门
            t_start = max(current_time[src_trap], current_time[dst_trap])
            t_end = t_start + T_ROUTE_SHORT  # 简化
            trap_timeline[dst_trap].append((t_start, t_end, f'{ancilla}→{target}', 'route'))
            current_time[dst_trap] = t_end

    # 画甘特图
    colors = {'gate': C_GATE, 'route': C_ROUTE}
    max_time = max(t for tl in trap_timeline.values() for s, e, _, _ in tl for t in [e]) if any(trap_timeline.values()) else 100

    for t_name in trap_list:
        y = trap_idx[t_name]
        for (t_start, t_end, label, op_type) in trap_timeline[t_name]:
            ax.barh(y, t_end - t_start, left=t_start, height=0.6,
                    color=colors[op_type], alpha=0.8, edgecolor='white', linewidth=0.5)
            ax.text(t_start + (t_end - t_start)/2, y, label,
                    ha='center', va='center', fontsize=7, fontweight='bold', color='white')

    ax.set_yticks(range(len(trap_list)))
    ax.set_yticklabels(trap_list)
    ax.set_xlabel('Time (μs)')
    ax.set_title(title, fontsize=11, fontweight='bold')
    ax.set_xlim(0, max_time * 1.1)
    ax.invert_yaxis()
    ax.grid(axis='x', alpha=0.3)

def make_cnot_sequence(assignment):
    """生成 CNOT 执行序列（按 ancilla 顺序）"""
    seq = []
    for ancilla, targets in ANCILLA_CNOTS.items():
        for target in targets:
            seq.append((ancilla, target))
    return seq

def generate_figure(c_value, assignment, filename):
    """为某个 C 值生成完整图"""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # 左图：Grid + qubit + trap + 路由
    draw_grid(axes[0], f'C={c_value} Qubit Layout & Routing')
    draw_traps(axes[0], assignment)
    seq = make_cnot_sequence(assignment)
    draw_routes(axes[0], assignment, seq)

    # 右图：时间线
    draw_timeline(axes[1], assignment, seq, f'C={c_value} Execution Timeline')

    # 图例
    legend_elements = [
        mpatches.Patch(facecolor=C_DATA, label='Data Qubit'),
        mpatches.Patch(facecolor=C_ANCILLA, label='Ancilla Qubit'),
        mpatches.Patch(facecolor=C_GATE, label='Local Gate'),
        mpatches.Patch(facecolor=C_ROUTE, label='Routing + Gate'),
        mpatches.Patch(facecolor=C_JUNCTION, alpha=0.3, label='Junction'),
    ]
    fig.legend(handles=legend_elements, loc='lower center', ncol=5,
               fontsize=9, bbox_to_anchor=(0.5, -0.02))

    plt.tight_layout()
    filepath = os.path.join(OUT_DIR, filename)
    fig.savefig(filepath, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {filepath}")
    return filepath

def main():
    files = []
    files.append(generate_figure(2, ASSIGN_C2, "qccd_c2_routing.png"))
    files.append(generate_figure(3, ASSIGN_C3, "qccd_c3_routing.png"))
    files.append(generate_figure(4, ASSIGN_C4, "qccd_c4_routing.png"))

    # 综合对比图
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))

    configs = [(2, ASSIGN_C2), (3, ASSIGN_C3), (4, ASSIGN_C4)]
    for col, (c_val, assign) in enumerate(configs):
        # 上排：Grid
        ax_grid = axes[0, col]
        draw_grid(ax_grid, f'C={c_val}')
        draw_traps(ax_grid, assign)
        seq = make_cnot_sequence(assign)
        draw_routes(ax_grid, assign, seq)

        # 下排：Timeline
        ax_time = axes[1, col]
        draw_timeline(ax_time, assign, seq, f'C={c_val} Timeline')

    plt.tight_layout()
    comparison_path = os.path.join(OUT_DIR, "qccd_comparison.png")
    fig.savefig(comparison_path, dpi=150, bbox_inches='tight')
    plt.close()
    files.append(comparison_path)
    print(f"Saved: {comparison_path}")

    return files

if __name__ == '__main__':
    main()
