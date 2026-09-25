from fastapi import APIRouter, HTTPException

from app.repositories.gtfs_repository import GTFSRepository


def create_routes_router(
    repository: GTFSRepository,
) -> APIRouter:

    router = APIRouter(
        prefix="/routes",
        tags=["Routes"],
    )

    # =========================================================
    # GET /api/routes
    # =========================================================

    @router.get("")
    def get_routes():
        """
        Получить все маршруты.
        """

        routes = repository.get_routes()

        return {
            "count": len(routes),
            "routes": routes,
        }

    # =========================================================
    # GET /api/routes/number/{route_number}
    # =========================================================

    @router.get("/number/{route_number}")
    def get_route_by_number(
        route_number: str,
    ):
        """
        Получить маршрут по короткому номеру.

        Например:

        /api/routes/number/1
        """

        routes = repository.get_route_by_number(
            route_number
        )

        if not routes:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Маршрут №{route_number} "
                    "не найден"
                ),
            )

        return routes[0]

    # =========================================================
    # GET /api/routes/{route_id}
    # =========================================================

    @router.get("/{route_id}")
    def get_route(
        route_id: str,
    ):
        """
        Получить маршрут по GTFS route_id.

        Например:

        /api/routes/4450
        """

        routes = repository.get_route(
            route_id
        )

        if not routes:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Маршрут с route_id={route_id} "
                    "не найден"
                ),
            )

        return routes[0]

    return router