"""Tool schema definitions for all tools (Cursor/Copilot-style)."""

from src.tools.tool_schema import ParameterSchema, ToolSchema


def get_finance_tool_schema() -> ToolSchema:
    """Schema for finance tool."""
    return ToolSchema(
        name="finance_tool",
        description="Manage financial accounts, transactions, transfers, and summaries. Supports creating accounts, adding transactions, transferring funds, listing accounts, viewing balances, and generating summaries.",
        parameters=[
            ParameterSchema(
                name="operation",
                type="string",
                description="The finance operation to perform",
                required=True,
                enum=["create_account", "list_accounts", "get_account", "add_transaction", "transfer", "show_balance", "transaction_history", "monthly_summary", "category_summary", "update_account", "delete_account"],
                examples=["create_account", "transfer", "show_balance"],
            ),
            ParameterSchema(
                name="account_name",
                type="string",
                description="Name of the account (e.g., 'savings', 'checking', 'wallet')",
                required=False,
                examples=["savings", "checking", "axis", "wallet"],
            ),
            ParameterSchema(
                name="amount",
                type="number",
                description="Monetary amount",
                required=False,
                examples=[1000, 500.50, 2000],
            ),
            ParameterSchema(
                name="opening_balance",
                type="number",
                description="Initial balance when creating account",
                required=False,
                default=0.0,
                examples=[10000, 5000, 0],
            ),
            ParameterSchema(
                name="kind",
                type="string",
                description="Transaction type: 'credit' (money in) or 'debit' (money out)",
                required=False,
                enum=["credit", "debit"],
                examples=["credit", "debit"],
            ),
            ParameterSchema(
                name="source_account",
                type="string",
                description="Source account name for transfers",
                required=False,
                examples=["savings", "checking"],
            ),
            ParameterSchema(
                name="target_account",
                type="string",
                description="Target account name for transfers",
                required=False,
                examples=["wallet", "checking"],
            ),
            ParameterSchema(
                name="year",
                type="integer",
                description="Year for monthly summary",
                required=False,
                examples=[2026, 2025],
            ),
            ParameterSchema(
                name="month",
                type="integer",
                description="Month (1-12) for monthly summary",
                required=False,
                examples=[1, 2, 12],
            ),
            ParameterSchema(
                name="transaction_id",
                type="integer",
                description="Transaction ID for update/delete operations",
                required=False,
                examples=[1, 5, 10],
            ),
            ParameterSchema(
                name="new_account_name",
                type="string",
                description="New name when renaming account",
                required=False,
                examples=["emergency_fund", "new_savings"],
            ),
        ],
        returns={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "output_text": {"type": "string"},
                "data": {"type": "object"},
            },
        },
        examples=[
            {
                "description": "Create account with opening balance",
                "input": {"operation": "create_account", "account_name": "savings", "opening_balance": 10000},
                "output": {"success": True, "output_text": "Created account savings with opening balance Rs 10000.00."},
            },
            {
                "description": "Transfer money",
                "input": {"operation": "transfer", "amount": 500, "source_account": "savings", "target_account": "wallet"},
                "output": {"success": True, "output_text": "Transferred Rs 500.00 from savings to wallet."},
            },
        ],
        error_codes={
            "INSUFFICIENT_BALANCE": "Source account doesn't have enough balance",
            "ACCOUNT_NOT_FOUND": "Account doesn't exist",
            "INVALID_AMOUNT": "Amount must be positive",
        },
    )


def get_reminder_tool_schema() -> ToolSchema:
    """Schema for reminder tool."""
    return ToolSchema(
        name="reminder_tool",
        description="Create, list, update, and delete reminders. Supports natural language date/time parsing.",
        parameters=[
            ParameterSchema(
                name="operation",
                type="string",
                description="Reminder operation",
                required=True,
                enum=["create", "list", "update", "delete", "mark_done"],
                examples=["create", "list"],
            ),
            ParameterSchema(
                name="title",
                type="string",
                description="Reminder title/description",
                required=False,
                examples=["Call mom", "Buy groceries", "Review project"],
            ),
            ParameterSchema(
                name="due_at",
                type="string",
                description="Due date/time in ISO format or natural language (e.g., 'tomorrow at 5 pm', 'next Monday')",
                required=False,
                examples=["2026-02-21T17:00:00Z", "tomorrow at 5 pm", "next Monday"],
            ),
            ParameterSchema(
                name="reminder_id",
                type="integer",
                description="Reminder ID for update/delete operations",
                required=False,
                examples=[1, 5],
            ),
            ParameterSchema(
                name="include_done",
                type="boolean",
                description="Include completed reminders in list",
                required=False,
                default=False,
            ),
        ],
        returns={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "output_text": {"type": "string"},
                "data": {"type": "object"},
            },
        },
        examples=[
            {
                "description": "Create reminder",
                "input": {"operation": "create", "title": "Call mom", "due_at": "tomorrow at 5 pm"},
                "output": {"success": True, "output_text": "Reminder saved: 'Call mom' at 2026-02-21 17:00."},
            },
        ],
    )


def get_calendar_tool_schema() -> ToolSchema:
    """Schema for calendar tool."""
    return ToolSchema(
        name="calendar_tool",
        description="Schedule events, list upcoming events, and manage calendar entries.",
        parameters=[
            ParameterSchema(
                name="operation",
                type="string",
                description="Calendar operation",
                required=True,
                enum=["schedule", "list", "delete"],
                examples=["schedule", "list"],
            ),
            ParameterSchema(
                name="title",
                type="string",
                description="Event title",
                required=False,
                examples=["Design review", "Team meeting", "Doctor appointment"],
            ),
            ParameterSchema(
                name="start_at",
                type="string",
                description="Start date/time in ISO format or natural language",
                required=False,
                examples=["2026-02-21T10:00:00Z", "tomorrow at 10 am", "Monday 2 pm"],
            ),
            ParameterSchema(
                name="duration_hours",
                type="number",
                description="Event duration in hours",
                required=False,
                default=1.0,
                examples=[1, 2, 0.5],
            ),
            ParameterSchema(
                name="event_id",
                type="integer",
                description="Event ID for delete operations",
                required=False,
            ),
        ],
        returns={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "output_text": {"type": "string"},
                "data": {"type": "object"},
            },
        },
    )


def get_people_tool_schema() -> ToolSchema:
    """Schema for people tool."""
    return ToolSchema(
        name="people_tool",
        description="Store and retrieve information about people, relationships, and contacts.",
        parameters=[
            ParameterSchema(
                name="operation",
                type="string",
                description="People operation",
                required=True,
                enum=["add", "get", "list", "delete"],
                examples=["add", "get", "list"],
            ),
            ParameterSchema(
                name="name",
                type="string",
                description="Person's name",
                required=False,
                examples=["Roy", "Ravi", "John"],
            ),
            ParameterSchema(
                name="relationship",
                type="string",
                description="Relationship type (e.g., 'friend', 'manager', 'brother')",
                required=False,
                examples=["friend", "manager", "brother", "colleague"],
            ),
            ParameterSchema(
                name="notes",
                type="string",
                description="Additional notes about the person",
                required=False,
                examples=["Joyful nature", "Works at Google", "Lives in NYC"],
            ),
        ],
        returns={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "output_text": {"type": "string"},
                "data": {"type": "object"},
            },
        },
    )


def get_all_tool_schemas() -> list[ToolSchema]:
    """Get schemas for all tools."""
    return [
        get_finance_tool_schema(),
        get_reminder_tool_schema(),
        get_calendar_tool_schema(),
        get_people_tool_schema(),
    ]
