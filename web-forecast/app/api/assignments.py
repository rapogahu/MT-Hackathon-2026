from fastapi import APIRouter

from app.repositories.gtfs_repository import GTFSRepository


def create_assignments_router(
    repository: GTFSRepository,
) -> APIRouter:

    router = APIRouter(
        prefix="/assignments",
        tags=["Assignments"],
    )

    # =========================================================
    # GET /api/assignments
    # =========================================================

    @router.get("")
    def get_assignments(
        route_id: str | None = None,
        date: str | None = None,
    ):
        """
        Получить наряды.

        Примеры:

        /api/assignments

        /api/assignments?route_id=4450

        /api/assignments?route_id=4450&date=20260208
        """

        assignments = repository.get_assignments(
            route_id=route_id,
            date=date,
        )

        return {
            "count": len(assignments),
            "filters": {
                "route_id": route_id,
                "date": date,
            },
            "assignments": assignments,
        }

    # =========================================================
    # GET /api/assignments/routes/{route_id}
    # =========================================================

    @router.get("/routes/{route_id}")
    def get_route_assignments(
        route_id: str,
        date: str | None = None,
    ):
        """
        Наряды конкретного маршрута.

        Например:

        /api/assignments/routes/4450

        /api/assignments/routes/4450?date=20260208
        """

        assignments = repository.get_assignments(
            route_id=route_id,
            date=date,
        )

        return {
            "route_id": route_id,
            "date": date,
            "count": len(assignments),
            "vehicles": assignments,
        }

    return router