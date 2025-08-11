## Examples

### Run the Manus agent programmatically
```python
import asyncio
from app.agent.manus import Manus

async def main():
    agent = await Manus.create()
    await agent.run("Create a markdown file /workspace/hello.md with a greeting")
    await agent.cleanup()

asyncio.run(main())
```

### Use tools directly
```python
import asyncio
from app.tool import ToolCollection
from app.tool.web_search import WebSearch
from app.tool.str_replace_editor import StrReplaceEditor

async def main():
    tools = ToolCollection(WebSearch(), StrReplaceEditor())
    res = await tools.execute(name="web_search", tool_input={"query": "OpenManus"})
    print(res.output)

asyncio.run(main())
```

### Planning flow
```python
import asyncio
from app.agent.manus import Manus
from app.flow.flow_factory import FlowFactory, FlowType

async def main():
    flow = FlowFactory.create_flow(FlowType.PLANNING, agents={"manus": Manus()})
    result = await flow.execute("Plan: generate outline and write a draft")
    print(result)

asyncio.run(main())
```