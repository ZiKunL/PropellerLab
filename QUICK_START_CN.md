# PropellerLab 中文快速操作指南

本文档面向软件使用者，用于快速启动 PropellerLab，并完成常见的螺旋桨计算、XFOIL polar 生成、优化设计和目标优化流程。

## 1. 启动软件

项目位置：

```text
D:\CodexProjects\PropellerLab
```

推荐使用已经创建好的 Miniconda 环境 `prop_env`：

```powershell
cd D:\CodexProjects\PropellerLab
D:\Application\miniconda\Scripts\conda.exe run -n prop_env python -m propeller_lab.main
```

如果需要验证环境是否正常：

```powershell
D:\Application\miniconda\Scripts\conda.exe run -n prop_env python -m pytest
```

## 2. 软件主界面

顶部 `Workspace` 用于切换工作区：

- `Base Calculate`：基础螺旋桨性能计算
- `Optimization Design`：基于翼型特性的初步扭转设计
- `Target Optimization`：按推力、扭矩、功率限制等目标自动优化几何

一般建议从 `Base Calculate` 开始，先确认当前几何和工况能正常计算，再进入设计或目标优化。

## 3. Base Calculate 快速计算

### 3.1 输入几何参数

常用输入：

- `Blades B`：桨叶数
- `Diameter D, m`：螺旋桨直径
- `Hub diameter, m`：桨毂直径
- `Pitch P, m`：几何桨距
- `Pitch angle at 70%R, deg`：70% 半径处桨距角
- `Root chord, m`：根部弦长
- `Tip chord, m`：尖部弦长
- `Elements`：径向离散段数

`Pitch P, m` 和 `Pitch angle at 70%R, deg` 二选一使用。输入桨距角后，软件会自动换算成等效 Pitch。

### 3.2 输入工况

常用输入：

- `RPM`：转速
- `V_inf, m/s`：来流速度，静拉力可填 0
- `Density rho`：流体密度
- `Dynamic viscosity mu`：动力黏度

### 3.3 选择计算模型

推荐 `Solver mode` 使用 `auto`。

`auto` 会自动判断低速、静拉力或前飞工况。静拉力或近静拉力时，软件会自动避开普通前飞 BEMT 中的低速奇异问题。

### 3.4 执行计算

点击：

```text
Calculate
```

计算后查看：

- `Summary`：总推力、扭矩、功率、效率、CT/CQ/CP
- `Stations`：每个径向站位的局部结果
- `Load plots`：载荷分布
- `Aero plots`：迎角、雷诺数、马赫数等气动状态

## 4. Polar 数据选择

PropellerLab 可使用三类 polar：

- `GenericPolar`：内置简化通用翼型数据
- `Imported polar`：用户导入的 CSV polar
- `XFOIL polar`：通过外部 XFOIL 生成的数据

注意：`GenericPolar` 不是 NACA 4412、Clark Y 或任何真实翼型，只是兜底通用模型。需要真实翼型比较时，应使用 XFOIL 或导入 polar 数据。

## 5. XFOIL 快速使用

### 5.1 设置 XFOIL 路径

在 `Base Calculate` 的 XFOIL 区域中，设置 `xfoil.exe` 路径。

如果点击检查时提示：

```text
XFOIL executable was not found.
```

说明当前路径找不到 XFOIL，需要重新选择或下载 XFOIL。

### 5.2 选择翼型来源

支持：

- `NACA`：输入如 `4412`、`6412`
- `DAT file`：选择翼型坐标 `.dat` 文件

### 5.3 设置雷诺数

可以手动设置 Reynolds，也可以点击：

```text
Estimate Re range
```

软件会根据当前 RPM、直径、弦长、来流速度、密度和黏度估算叶片工作雷诺数范围。

若启用：

```text
Use multi-Re sweep
```

软件会让 XFOIL 在多个代表性 Reynolds 下计算 polar。后续 BEMT 计算时，每个径向站位会按自己的 Reynolds 插值。

### 5.4 生成并使用 polar

点击：

```text
Run XFOIL
```

完成后可以：

- `Save polar CSV`：保存 polar 文件
- `Use as current polar`：把生成的 polar 用作当前计算 polar

保存文件建议放在：

```text
data\airfoils\
```

## 6. 导入和导出

常用按钮：

- `Import geometry CSV`：导入桨叶几何
- `Export geometry CSV`：导出当前几何
- `Import polar CSV`：导入 polar
- `Export station CSV`：导出站位计算结果
- `Export summary CSV`：导出总性能结果
- `Export RPM sweep CSV`：导出转速扫描结果

本地数据建议保存到：

```text
data\airfoils\
data\blade_geometries\
data\designs\
```

这些目录中的用户数据默认不会被 Git 提交。

## 7. RPM Sweep

在 `Base Calculate` 中设置 RPM sweep 范围后运行扫描，可用于观察不同转速下的：

- 推力
- 扭矩
- 功率
- 效率
- CT/CQ/CP

扫描前建议先用单点 `Calculate` 确认几何和 polar 正常。

## 8. Optimization Design 快速流程

`Optimization Design` 用于快速生成一个初步扭转分布。

推荐流程：

1. 在 `Base Calculate` 中先完成一次正常计算。
2. 切换到 `Optimization Design`。
3. 选择设计方法，例如 `Max Cl/Cd Twist Design`。
4. 设置 alpha 搜索范围和约束。
5. 如需目标推力或目标功率，选择对应目标模式。
6. 点击 `Generate design`。
7. 查看设计结果和站位表。
8. 点击 `Analyze generated design` 复算性能。
9. 满意后点击 `Apply design to Base Calculate`。

注意：Optimization Design 是初步 twist 设计，不是完整全局最优设计。

## 9. Target Optimization 快速流程

`Target Optimization` 用于按目标自动搜索 chord/R、beta 和可选直径 D。

### 9.1 单翼型目标优化

推荐流程：

1. 在 `Base Calculate` 中设置基础几何和工况。
2. 切换到 `Target Optimization`。
3. 点击 `Copy Base Calculate inputs`。
4. 设置目标模式：
   - `Target thrust, minimize power`
   - `Target thrust with torque limit`
   - `Target torque, maximize thrust`
   - `Match thrust`
   - `Match torque`
5. 输入目标推力或目标扭矩。
6. 设置 RPM、V_inf、桨叶数、直径和约束范围。
7. 设置 chord/R 范围和 beta 范围。
8. 选择优化方法：
   - `Random search`
   - `Genetic algorithm`
   - `GA + local refine`
9. 点击 `Run target optimization`。
10. 查看 summary、history、best geometry 和 warning。
11. 满意后点击 `Apply best to Base Calculate`。

### 9.2 直径范围优化

Target Optimization 中有三个直径相关输入：

- `Diameter D, m`：参考直径
- `Diameter min D, m`：允许搜索的最小直径
- `Diameter max D, m`：允许搜索的最大直径

若要固定直径：

```text
Diameter min D, m = Diameter max D, m
```

若要让优化器自动选择直径：

```text
Diameter min D, m < Diameter max D, m
```

优化完成后，summary 中的：

```text
best diameter D, m
```

就是最终选中的直径。点击 `Apply best to Base Calculate` 后，该直径会写回基础计算界面。

### 9.3 Hybrid root-to-tip 混合翼型

用途：同一支桨从根部到尖部使用多个不同翼型。

流程：

1. `Airfoil optimization mode` 选择 `Hybrid root-to-tip`。
2. 选择 `Airfoil source`：
   - `NACA list`
   - `DAT files`
3. 如果使用 NACA，可输入：

```text
4412, 4612, 0012
```

4. 如果使用 DAT，每行输入一个 DAT 文件路径，顺序为 root 到 tip。
5. 点击 `Estimate optimization Re`。
6. 点击 `Build target XFOIL polars`。
7. XFOIL 完成后运行目标优化。

### 9.4 Compare uniform airfoils 翼型对比

用途：比较多个“整支桨都使用同一种翼型”的方案。

例如比较：

```text
NACA 4412
NACA 6412
Clark Y DAT
```

流程：

1. `Airfoil optimization mode` 选择 `Compare uniform airfoils`。
2. NACA 输入框可填：

```text
4412, 6412
```

3. DAT files 中可填一个或多个 `.dat` 路径。
4. 点击 `Estimate optimization Re`。
5. 点击 `Build target XFOIL polars`。
6. 点击 `Run target optimization`。
7. 查看 `Airfoil comparison` 表。

`Airfoil comparison` 会显示：

- 排名
- airfoil_id
- 最佳直径 D
- fitness
- 目标误差
- 推力、扭矩、功率、效率
- CT/CQ/CP
- evaluations
- warnings_count

排名第一的候选会自动成为当前 best result，可直接应用或导出。

## 10. 如何判断结果是否可信

不要只看推力是否达到目标，还应检查：

- `target error` 是否足够小
- `warnings` 是否提示目标不可达
- `max alpha` 是否过高
- `stall fraction` 是否过大
- `low Re fraction` 是否过大
- `max Mach` 是否接近压缩性风险区
- 几何是否过度扭曲或弦长不现实
- power limit 是否被违反

若目标过于极端，例如很小直径、很低 RPM 却要求巨大推力，优化器可能会给出不可达 warning。此时应放宽直径、RPM、功率限制或几何边界。

## 11. 常见问题

### 11.1 没有 XFOIL 时能算吗？

可以。软件会使用 `GenericPolar` 或已导入的 polar。

但如果要比较真实翼型，例如 NACA 4412 与 Clark Y，建议使用 XFOIL 或导入真实 polar。

### 11.2 XFOIL 失败怎么办？

检查：

- `xfoil.exe` 路径是否正确
- DAT 文件格式是否正确
- alpha 范围是否过大
- Reynolds 是否过低或过高
- 翼型是否需要重新 panel

必要时缩小 alpha 范围，例如：

```text
alpha start = -4
alpha end = 12
alpha step = 1
```

### 11.3 优化卡住或很慢怎么办？

可以先降低：

- `Population`
- `Generations`
- `Elements`
- `Control points`
- `Target Re count`

先用小规模确认流程，再提高精度。

### 11.4 什么时候用 Random search？

快速试探边界或检查目标是否大致可达时使用。

### 11.5 什么时候用 GA + local refine？

在参数范围已经比较合理、希望进一步细化结果时使用。

## 12. 推荐的完整操作顺序

新项目建议按以下顺序：

1. 在 `Base Calculate` 输入几何和工况。
2. 用 `GenericPolar` 先跑通一次。
3. 估算 Re 范围。
4. 用 XFOIL 生成目标翼型 polar。
5. `Use as current polar` 后重新 Calculate。
6. 若需要初步扭转设计，进入 `Optimization Design`。
7. 若有明确推力、扭矩或功率目标，进入 `Target Optimization`。
8. 优化完成后 Apply 回 `Base Calculate`。
9. 再次 Calculate 验证。
10. 导出 summary、station、geometry 或 optimization CSV。

## 13. 重要提醒

- PropellerLab 是工程估算工具，不是 CFD。
- XFOIL 是二维翼型工具，不包含三维旋转桨叶效应。
- 高迎角、低 Reynolds、高 Mach 和失速后结果需要谨慎。
- 优化结果依赖 polar 质量、边界范围、目标权重和随机种子。
- 重要设计必须通过实验或更高保真工具验证。

