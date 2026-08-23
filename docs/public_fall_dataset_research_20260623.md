# Public Fall Dataset Research - 2026-06-23

## Scope

本报告整理可用于后续 `hardneg_v1` 数据补充的公开跌倒检测数据集。当前仅做调研，不下载、不训练、不混入训练集。

## Recommended Priority

| Dataset | Recommendation | Main Use |
| --- | --- | --- |
| GMDCSA-24 | High | 已在本地存在，可继续做 fall / ADL 基础训练与验证，但需时间窗复核。 |
| UR Fall Detection Dataset | High | 小而清晰，适合 sanity check 与公共基准，但 ADL 类型有限。 |
| Multiple Cameras Fall Dataset | High | 包含坐、蹲、躺沙发等 confounding events，适合 hard negative。 |
| FallVision | Medium-High | 新数据集，包含 fall/no-fall 分类和不同跌倒来源，适合补充多样性；下载前确认许可。 |
| OmniFall | Medium-High | 统一多数据集与 temporal segmentation，适合作为标注规范和跨域评测参考。 |
| UP-Fall Detection Dataset | Medium | 多模态/多摄像头，适合补充参考；需确认可用视频模态和许可。 |

## Dataset Notes

### GMDCSA-24

来源：

- GitHub: https://github.com/ekramalam/GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos
- Zenodo: https://zenodo.org/records/12921216
- PubMed: https://pubmed.ncbi.nlm.nih.gov/39309713/

公开信息摘要：

- 面向 human fall detection in videos。
- Zenodo v2.0 包约 1.1 GB。
- GitHub README 引用 Data in Brief 与 Zenodo DOI。
- 本地已存在 `datasets/gmdcsa24`，扫描到 224 个视频。

本项目用途：

- 可作为 fall / ADL 公共基础数据。
- 需要按 actor 分组，防止 train/test leakage。
- 对 fall 样本补 `fall_start_sec/fall_end_sec` 后再进入 hardneg_v1 或 temporal 阶段。

风险：

- 本地历史报告显示 ADL 子类较粗，容易统一成 walk/unknown_adl。
- 不能只靠路径规则直接训练，必须做 split 与标签 QA。

### UR Fall Detection Dataset

来源：

- Official page: https://fenix.ur.edu.pl/~mkepski/ds/uf.html

公开信息摘要：

- 包含 70 个序列：30 falls + 40 ADL。
- fall 事件由 2 台 Microsoft Kinect 摄像头和加速度数据记录。
- ADL 事件由 camera 0 和加速度计记录。

本项目用途：

- 适合做公共 sanity check。
- 适合保留一部分作为 public_test，验证 hardneg_v1 没有牺牲召回。

风险：

- 数据量较小。
- ADL 覆盖有限，不能解决本地 sit/squat/no_person 全部误报。

### Multiple Cameras Fall Dataset

来源：

- Official page: https://www.iro.umontreal.ca/~labimage/Dataset/

公开信息摘要：

- 24 个场景，8 个 IP 摄像头。
- 前 22 个场景包含 fall 和 confounding events，后 2 个包含 confounding events。
- 论文材料描述了 crouching、sitting、lying on a sofa 等 confounding events。

本项目用途：

- 非常适合补充 hard negative：sit、squat/crouch、lie_down_non_fall、occlusion、多视角。
- 适合训练后做跨摄像头误报评测。

风险：

- 数据较老，分辨率/画面风格与当前本地摄像头可能不同。
- 需要按 scenario/camera 分组，避免同一场景多摄像头泄漏到不同 split。

### FallVision

来源：

- PubMed: https://pubmed.ncbi.nlm.nih.gov/40160526/
- PMC: https://pmc.ncbi.nlm.nih.gov/articles/PMC11950752/

公开信息摘要：

- Data in Brief 2025 数据集。
- 文章介绍为面向 fall detection 的 categorized fall and no-fall video dataset。
- 摘要提到 fall 来源包括 bed、chair、standing position。

本项目用途：

- 可补充从床/椅子/站立状态跌倒的数据多样性。
- no-fall 视频可用于扩充 hard negative，但需要先确认类别细节。

风险：

- 下载入口、许可和原始视频结构需要训练前再次确认。
- 若提供的是 processed landmark videos，也要确认是否适合 YOLO fall detector 训练。

### OmniFall

来源：

- Paper: https://arxiv.org/abs/2505.19889
- Hugging Face dataset: https://huggingface.co/datasets/simplexsigil2/omnifall
- Code: https://github.com/simplexsigil/omnifall-experiments

公开信息摘要：

- 统一多个 staged fall datasets，约 14 小时录制、约 42 小时多视角视频、101 subjects、29 camera views。
- 提供一致 taxonomy 和 video segmentation labels。
- 包含 staged-to-wild 评测思想，用于衡量从受控环境到真实事故视频的泛化。

本项目用途：

- 优先作为标注规范、跨域评测和 temporal segmentation 参考。
- 可以帮助设计 fall / fallen / sit down / lie down / standing 等更细标签边界。

风险：

- 汇总数据集可能包含二次分发限制。
- 训练使用前必须逐源确认许可和文件访问规则。

### UP-Fall Detection Dataset

来源：

- Sensors paper: https://pmc.ncbi.nlm.nih.gov/articles/PMC6539235/
- Challenge UP data page: https://sites.google.com/up.edu.mx/challenge-up-2019/data

公开信息摘要：

- 多模态 fall detection 数据集。
- Challenge UP 页面描述为 11 个活动、3 次尝试、多个 subjects，包含 6 类日常活动和 5 类跌倒。
- 相关论文/资料描述其包含 wearable sensors、ambient sensors 和 vision devices。

本项目用途：

- 适合作为第二阶段 temporal / multimodal 参考。
- 可抽取 RGB camera 数据做公共补充，但优先级低于 MCFD hard negative。

风险：

- 多模态结构复杂，视频数据可用性和许可需要确认。
- 与当前单 RGB runtime 链路不完全一致。

## Data Addition Recommendation

优先补充顺序：

1. 本地采集 hard negative：sit、squat、bend、lie_down_non_fall、no_person、occlusion。
2. Multiple Cameras Fall Dataset：补 sitting、crouching、lying sofa、多摄像头 confounders。
3. GMDCSA-24：清洗本地已有数据，补 fall 时间窗，作为 public train/val/test 基础。
4. URFD：保持一部分为 public_test，避免过拟合本地数据。
5. FallVision：确认许可后补充 bed/chair/standing fall 与 no-fall。
6. OmniFall：优先借鉴 taxonomy 和 segmentation，不急于直接训练。
7. UP-Fall：作为 temporal/multimodal 后续参考。

## Training Readiness Conclusion

尚不建议直接开始训练 `models/yolo_fall_detector_hardneg_v1.pt`。

最小训练前门槛：

- 完成本地 hard negative 补采或确认，特别是 sit/squat/bend/lie_down_non_fall/no_person。
- 补齐 fall 样本 `fall_start_sec/fall_end_sec`。
- 冻结 held-out 集：2026-06-23 labeled validation 12 条、URFD/GMDCSA public_test 子集、当前 FP regression set。
- 每个公开数据集确认许可、来源、分组 split。
- 生成最终训练 manifest，而不是直接从 `datasets/` 递归读入。
