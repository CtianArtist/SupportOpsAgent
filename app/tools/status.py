from app.db.models import ServiceStatus
from app.tools.context import ToolContext
from app.tools.schemas import EmptyInput, ServiceStatusData


def check_service_status(arguments: EmptyInput, context: ToolContext) -> list[ServiceStatusData]:
    rows = context.db.query(ServiceStatus).order_by(ServiceStatus.service).all()
    return [
        ServiceStatusData(
            service=row.service,
            status=row.status,
            note=row.note,
            updated_at=row.updated_at,
        )
        for row in rows
    ]