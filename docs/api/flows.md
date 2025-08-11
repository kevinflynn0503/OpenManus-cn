## Flows API

### BaseFlow (`app.flow.base.BaseFlow`)
- Purpose: multi-agent execution flow base
- Fields: `agents: dict[str, BaseAgent]`, `tools: list | None`, `primary_agent_key: str | None`
- Methods:
  - `get_agent(key: str) -> BaseAgent | None`
  - `add_agent(key: str, agent: BaseAgent) -> None`
  - `primary_agent -> BaseAgent | None`
  - `async execute(input_text: str) -> str` (abstract)

### PlanningFlow (`app.flow.planning.PlanningFlow`)
- Manages planning and step execution
- Fields: `llm: LLM`, `planning_tool: PlanningTool`, `executor_keys: list[str]`, `active_plan_id: str`, `current_step_index: int | None`
- Methods:
  - `get_executor(step_type: str | None = None) -> BaseAgent`
  - `async execute(input_text: str) -> str`

Example:
```python
from app.agent.manus import Manus
from app.flow.flow_factory import FlowFactory, FlowType
agents = {"manus": Manus()}
flow = FlowFactory.create_flow(FlowType.PLANNING, agents)
result = await flow.execute("Generate an outline and draft a README")
```

### FlowFactory (`app.flow.flow_factory.FlowFactory`)
- `create_flow(flow_type: FlowType, agents: BaseAgent | list[BaseAgent] | dict[str, BaseAgent], **kwargs) -> BaseFlow`
- `FlowType.PLANNING`