# Cache Behavior

缓存实验与核心基准分开统计；疑似缓存命中不会进入真实事件延迟归因。

## C1_exact_repeat

| Run | Prompt eval ms | Total ms | Cache hit suspected |
|---:|---:|---:|:---:|
| 1 | 5079.94 | 5442.16 | False |
| 2 | 579.53 | 604.61 | True |
| 3 | 596.60 | 620.44 | True |
| 4 | 588.96 | 613.35 | True |
| 5 | 581.93 | 601.53 | True |

## C2_prompt_nonce

| Run | Prompt eval ms | Total ms | Cache hit suspected |
|---:|---:|---:|:---:|
| 1 | 5095.01 | 5126.85 | False |
| 2 | 5121.58 | 5155.86 | False |
| 3 | 5046.47 | 5073.63 | False |
| 4 | 5007.12 | 5036.22 | False |
| 5 | 5042.31 | 5071.33 | False |

## C3_reencoded_images

| Run | Prompt eval ms | Total ms | Cache hit suspected |
|---:|---:|---:|:---:|
| 1 | 5028.58 | 5369.28 | False |
| 2 | 5018.21 | 5402.10 | False |
| 3 | 575.33 | 933.72 | True |
| 4 | 557.87 | 939.01 | True |
| 5 | 586.08 | 966.81 | True |

## C4_one_pixel_change

| Run | Prompt eval ms | Total ms | Cache hit suspected |
|---:|---:|---:|:---:|
| 1 | 573.48 | 949.93 | True |
| 2 | 559.68 | 588.34 | True |
| 3 | 560.19 | 586.26 | True |
| 4 | 549.40 | 567.01 | True |
| 5 | 5063.72 | 5410.80 | False |

## C5_new_event_frames

| Run | Prompt eval ms | Total ms | Cache hit suspected |
|---:|---:|---:|:---:|
| 1 | 5069.96 | 5431.50 | False |
| 2 | 5030.39 | 5051.89 | False |
| 3 | 5048.13 | 5075.33 | False |
| 4 | 5108.35 | 5134.85 | False |
| 5 | 5080.18 | 5105.58 | False |

## Interpretation rule

- 完全相同输入显著加速：疑似完整前缀或图像提示缓存。
- Prompt 起始位置变化后恢复正常：文本前缀缓存被破坏。
- JPEG bytes 变化后恢复正常：缓存包含图像输入字节或视觉前缀。
- 改一个像素后恢复正常：缓存对图像内容敏感。
