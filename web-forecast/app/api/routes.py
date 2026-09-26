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
    # GET /api/routes/number/{route_number}/stops
    # =========================================================

    @router.get("/number/{route_number}/stops")
    def get_route_stops(
        route_number: str,
    ):
        """
        Получить остановки маршрута
        с координатами.

        Например:

        /api/routes/number/1/stops
        """

        # -----------------------------------------------------
        # 1. Находим маршрут по его номеру
        # -----------------------------------------------------

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

        route = routes[0]

        # -----------------------------------------------------
        # 2. Получаем route_id
        # -----------------------------------------------------

        route_id = route["route_id"]

        # -----------------------------------------------------
        # 3. Получаем все остановки маршрута
        # -----------------------------------------------------

        stops = repository.get_trip_stops(
            route_id=route_id
        )

        if not stops:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Для маршрута №{route_number} "
                    "не найдены остановки"
                ),
            )

        # -----------------------------------------------------
        # 4. Разделяем остановки по направлениям
        # -----------------------------------------------------

        directions = {}

        for stop in stops:
            direction_id = str(
                stop["direction_id"]
            )

            if direction_id not in directions:
                directions[direction_id] = []

            directions[direction_id].append(
                stop
            )

        # -----------------------------------------------------
        # 5. Возвращаем маршрут и остановки
        # -----------------------------------------------------

        return {
            "route": route,
            "directions": directions,
        }
    # =========================================================
    # GET /api/routes/number/{route_number}/geometry
    # =========================================================

    @router.get(
        "/number/{route_number}/geometry"
    )
    def get_route_geometry(
        route_number: str,
    ):
        """
        Получить геометрию маршрута.
        """

        routes = (
            repository
            .get_route_by_number(
                route_number
            )
        )

        if not routes:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Маршрут №{route_number} "
                    "не найден"
                ),
            )

        route_id = str(
            routes[0]["route_id"]
        )

        geometry = (
            repository
            .get_route_geometry(
                route_id
            )
        )

        return {
            "route": (
                int(route_number)
                if route_number.isdigit()
                else route_number
            ),
            "route_id": route_id,
            "geometry": geometry,
        }

    # =========================================================
    # GET /api/routes/number/{route_number}/directions
    # =========================================================

    @router.get(
        "/number/{route_number}/directions"
    )
    def get_route_directions(
        route_number: str,
    ):
        """
        Получить направления маршрута.
        """

        routes = (
            repository
            .get_route_by_number(
                route_number
            )
        )

        if not routes:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Маршрут №{route_number} "
                    "не найден"
                ),
            )

        route_id = str(
            routes[0]["route_id"]
        )

        directions = (
            repository
            .get_route_directions(
                route_id
            )
        )

        return {
            "route": (
                int(route_number)
                if route_number.isdigit()
                else route_number
            ),
            "route_id": route_id,
            "directions": directions,
        }

    # =========================================================
    # GET /api/routes/number/{route_number}/stops
    # =========================================================

    @router.get(
        "/number/{route_number}/stops"
    )
    def get_route_stops(
        route_number: str,
    ):
        """
        Получить остановки маршрута.
        """

        routes = (
            repository
            .get_route_by_number(
                route_number
            )
        )

        if not routes:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Маршрут №{route_number} "
                    "не найден"
                ),
            )

        route_id = str(
            routes[0]["route_id"]
        )

        stops = (
            repository
            .get_route_geometry(
                route_id
            )
        )

        return {
            "route": (
                int(route_number)
                if route_number.isdigit()
                else route_number
            ),
            "route_id": route_id,
            "count": len(stops),
            "stops": stops,
        }
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