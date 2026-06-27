# LangGraph-Algo-System 测试用例集

测试方式：复制输入字符串至 chat.py 或 API 调用，观察输出是否符合预期。

---

## 一、当前项目已实现

### 1.1 完整错误诊断

**说明**：用户有完整代码 + 报错信息，系统应走 error 路径。

```
用户输入：
====================
394 题，我的代码：
def decodeString(s):
    stack = []
    for char in s:
        if char == ']':
            # 处理
            pass
        stack.append(char)
    return ''.join(stack)

报错：IndexError: pop from empty list
====================
```

**预期**：intent=error，sufficiency≥0.8，Flash 快路径 → reviewer 输出诊断报告。

### 1.2 完整教学请求

**说明**：用户表达明确的学习诉求，附代码或题号。

```
用户输入：
====================
394 题，我用栈写的，但是不清楚怎么处理嵌套括号的情况，能讲一下思路吗？
我的代码：
def decodeString(s):
    stack = []
    for c in s:
        if c == ']':
            # 不知道怎么处理
            pass
        else:
            stack.append(c)
    return ''
====================
```

**预期**：intent=teach，sufficiency≥0.8，Flash → tutor 输出结构化教学。

### 1.3 完整解法请求

**说明**：用户明确要求给出解法。

```
用户输入：
====================
帮我写 394 题的 Python 解法，用栈实现
====================
```

**预期**：intent=generate，sufficiency≥0.8，Flash → generator 输出代码。

### 1.4 追加追问（多轮）

**说明**：用户在第一轮收到教学后，输入"然后呢"进行追问。

```

====================
然后呢
====================
```

**预期**：extractor 识别为简短追问 → 不走 LLM → fact_ledger 保留上一轮历史 → summarizer 拼接 → diagnosis 重新判定 → gatekeeper 检查材料。

### 1.5 信息不充分 → gatekeeper 追问

**说明**：用户输入不足以支撑任何角色的执行。

```
用户输入：
====================
帮我做道题
====================
```

**预期**：diagnosis: sufficiency<0.5 → gatekeeper: ask → "你需要告诉我题号或贴一下代码"。

### 1.6 超简输入 → 意图模糊 → gatekeeper 追问

**说明**：用户仅提供题号，无动作诉求。

```
用户输入：
====================
394
====================
```

**预期**：diagnosis: sufficiency≈0.3-0.5 → gatekeeper: <0.5 直接 ask → "你想了解 394 的解法、思路还是帮你 debug？"

### 1.7 有题号有代码无描述

**说明**：用户贴了题号和代码，但没说要什么。

```
用户输入：
====================
394 
def decodeString(s):
    stack = []
    curr_str = ""
    curr_num = 0
    for c in s:
        if c.isdigit():
            curr_num = curr_num * 10 + int(c)
        elif c == '[':
            stack.append((curr_str, curr_num))
            curr_str, curr_num = "", 0
        elif c == ']':
            prev_str, num = stack.pop()
            curr_str = prev_str + num * curr_str
        else:
            curr_str += c
    return curr_str
====================
```

**预期**：diagnosis: sufficiency≥0.5 → gatekeeper 检查材料 → 有代码有题号 → proceed → 按 intent（可能是 teach）走路径。

---

## 二、当前项目应该实现

### 2.1 多轮后意图切换

**说明**：用户第一轮请求 teach，第二轮在收到教学后转为 generate。

```
第一轮：
====================
讲一下 394 题的思路
====================

第二轮：
====================
好的我懂了，直接给我代码吧
====================
```

**预期**：第二轮 diagnosis 从 teach 切换为 generate，gatekeeper 重新判定。

### 2.2 矛盾输入检测

**说明**：用户给的代码和题号明显不匹配（代码是二叉树，题号是 394 字符串解码）。

```
用户输入：
====================
394 题，这是我的代码
class TreeNode:
    def __init__(self, val):
        self.val = val
        self.left = None
        self.right = None

def inorder(root):
    if not root:
        return
    inorder(root.left)
    print(root.val)
    inorder(root.right)
====================
```

**预期**：gatekeeper 检测到矛盾 → 追问"你贴的代码是二叉树遍历，和 394 题（字符串解码）不匹配，请确认题号或代码是否正确。"（目前未实现，属未来 expert_precheck 功能）

### 2.3 循环追问终止

**说明**：用户在 gatekeeper 追问三次后仍提供不充分信息。

```
第一轮：==================== 帮我解题 ====================
第二轮：==================== 就是解题啊 ====================
第三轮：==================== 你问那么多干嘛，解题就是了 ====================
第四轮：==================== 394 ====================
```

**预期**：gatekeeper 检测到连续追问循环 → 兜底降级 → 走 proceed 给一个可用的但不完美的答案（当前未实现，需 fact_ledger 上限管理）。

### 2.4 简洁疑问句

**说明**：用户输入极短但有明确意图。

```
用户输入：
====================
394 怎么做？
====================
```

**预期**：diagnosis: intent=teach，sufficiency≥0.5 → gatekeeper: 有明确动作诉求"怎么做"→ proceed。

### 2.5 无题号有代码

**说明**：用户只贴了代码，未提供题号。

```
用户输入：
====================
def solve(nums):
    n = len(nums)
    dp = [1] * n
    for i in range(n):
        for j in range(i):
            if nums[i] > nums[j]:
                dp[i] = max(dp[i], dp[j] + 1)
    return max(dp)
====================
```

**预期**：extractor 无题号 → fetcher 跳过 → diagnosis: 有代码无题号 → sufficiency≥0.5 → gatekeeper: material check → 没有题号可能影响 generate，根据 prompt 规则决定 ask 还是 proceed。

### 2.6 混合意图（潜在地雷）

**说明**：用户请求中同时包含 error 和 teach 的信号。

```
用户输入：
====================
我写了 394 的代码但是超时了，能教我优化吗？
def decodeString(s):
    # 用递归做的，很慢
    ...
====================
```

**预期**：diagnosis 需要选择主导意图。当前只支持单一 intent，可能分类为 error 或 teach 中的一种。

---

## 三、当前项目可能实现

### 3.1 多人协作场景

**说明**：用户 A 和用户 B 共享同一个对话上下文，分工解决一道题。

```
用户输入（用户A）：
====================
我来写主体逻辑，你帮我看看边界条件
====================

用户输入（用户B）：
====================
我看了一下，当 n=0 的时候你的代码会出错
====================
```

**预期**：系统需要区分不同用户，合并上下文。（超越当前单用户对话设计）

### 3.2 代码沙箱执行

**说明**：用户提交代码，要求系统运行并返回结果。

```
用户输入：
====================
跑一下我的代码，输入 s = "3[a2[c]]"，告诉我输出
def decodeString(s):
    ...
====================
```

**预期**：需要 sandbox 节点 → 执行 → 反思 → 输出。（规划中，尚未实现）

### 3.3 课程规划

**说明**：用户要求系统为一组题目制定学习路径。

```
用户输入：
====================
我想在一周内学会动态规划，帮我排一下 70、198、300、322、1143 的学习顺序
====================
```

**预期**：需要 planner 节点 → 根据依赖关系和难度排序 → 输出学习路线图。（超越当前单题问答设计）

### 3.4 代码对比

**说明**：用户提供两份解法，要求对比优劣。

```
用户输入：
====================
解法一：
def solve(nums):
    return sum(nums)

解法二：
def solve(nums):
    total = 0
    for n in nums:
        total += n
    return total

哪个好？
====================
```

**预期**：需要 compare 角色或 reviewer 的扩展模式。

### 3.5 无逻辑输入（压力测试）

**说明**：用户输入完全无意义的字符串。

```
用户输入：
====================
asdflkj 394 zxcv 讲一下 !@#$%^
====================
```

**预期**：extractor 提取 "394" → diagnosis: sufficiency<0.3 → gatekeeper: <0.5 直接 ask → 追问。

### 3.6 魔幻输入（幻觉边界）

**说明**：用户输入一个不存在的题号。

```
用户输入：
====================
LeetCode 99999 题怎么做？
====================
```

**预期**：fetcher 三优先级均无法找到 → 兜底文案 → diagnosis → gatekeeper 检查材料。
