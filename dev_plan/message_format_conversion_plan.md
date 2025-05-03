# 计划：历史消息格式转换 - 多文本 Parts 合并

**1. 目标:**
修改 `app/core/message_converter.py` 中的 `convert_messages` 函数，使其能够检测并合并单个消息 `content` 列表中包含的多个纯文本 `parts`，生成符合 Gemini API 要求的单一文本 `part`。

**2. 背景:**
当前系统在处理发送给 Gemini API 的历史消息时，会跳过包含多个纯文本 `parts` 的用户消息。为了避免上下文丢失并提高响应质量，需要转换这些消息的格式，将多个文本 `parts` 合并为一个。

**3. 识别关键代码:**

* **文件:** `app/core/message_converter.py`
* **函数:** `convert_messages(messages: List[Message], use_system_prompt=False)`
* **具体位置:** 在处理 `elif isinstance(content, list):` (大约 L103) 的代码块内部，在构建了临时的 `parts` 列表之后，但在将其添加到最终的 `gemini_history` 之前 (大约在 L163-L184 之间)。

**4. 详细转换逻辑:**

在 `convert_messages` 函数内，处理多部分内容 (`isinstance(content, list)`) 的逻辑块中，`if parts and not has_error_in_item:` 条件判断之后，但在角色映射之前，插入以下代码：

```python
    # --- BEGIN: 新增的多文本 parts 合并逻辑 ---
    text_parts = [p['text'] for p in parts if 'text' in p and len(p) == 1] # 提取所有纯文本 parts 的内容
    non_text_parts = [p for p in parts if 'text' not in p or len(p) > 1] # 保留所有非文本 parts (如图像)

    if len(text_parts) > 1:
        merged_text = "\n".join(text_parts) # 使用换行符合并文本
        # 记录合并操作
        logger.debug(f"消息 {i}: 检测到 {len(text_parts)} 个文本 parts，合并为一个。")
        # 构建新的 parts 列表，合并后的文本在前，后面跟非文本 parts
        merged_parts = [{"text": merged_text}] + non_text_parts
        parts = merged_parts # 使用合并后的 parts 列表
    # --- END: 新增的多文本 parts 合并逻辑 ---

    # 后续的角色映射和添加到 gemini_history 的逻辑将使用更新后的 `parts` 变量
```

**逻辑步骤:**

1. 提取所有纯文本 `parts` 的内容到 `text_parts`。
2. 提取所有非纯文本 `parts` 到 `non_text_parts`。
3. 如果 `text_parts` 数量大于 1，则：
    * 用换行符 `\n` 合并 `text_parts` 为 `merged_text`。
    * 记录调试日志。
    * 创建新的 `merged_parts` 列表，包含合并后的文本 `part` 和所有 `non_text_parts`。
    * 更新 `parts` 变量为 `merged_parts`。
4. 后续代码使用更新后的 `parts` 列表。

**5. 日志记录建议:**

* 在执行合并操作时，添加调试日志：
    `logger.debug(f"消息 {i}: 检测到 {len(text_parts)} 个文本 parts，合并为一个。")`

**6. 兼容性考虑:**

* **图像处理:** 合并逻辑仅针对文本 `parts`，与现有图像处理兼容。
* **角色处理:** 修改发生在角色映射和合并之前，不影响现有逻辑。
* **System Prompt:** 修改发生在系统提示处理阶段之后，不影响其提取。
* **错误处理:** 修改位于错误检查之后，不引入新的错误路径。
* **`gemini.py` 兼容性:** Code 模式分析确认，`app/core/gemini.py` 不直接调用 `convert_messages`，因此本次修改（不改变函数签名和返回值结构）与其完全兼容。
* **Tool Calls:** `message_converter.py` 不处理工具调用，此修改理论上不直接冲突。需在实施和测试阶段验证与工具调用处理逻辑（可能在 `request_processing.py` 或 `endpoints.py`）的最终集成。
* **其他模块:** 修改是局部的，只要调用方能正确处理 `convert_messages` 的标准输出即可。

**7. 下一步:**
此计划已完成制定和复核。下一步是切换到 Code 模式，根据此计划在 `app/core/message_converter.py` 中实施代码修改。
