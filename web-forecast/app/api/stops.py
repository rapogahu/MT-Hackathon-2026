from fastapi import APIRouter, HTTPException

from app.repositories.gtfs_repository import GTFSRepository


def create_stops_router(
    repository: GTFSRepository,
) -> APIRouter:

    router = APIRouter(
        prefix="/stops",
        tags=["Stops"],
    )

    # =========================================================
    # GET /api/stops
    # =========================================================

    @router.get("")
    def get_stops():
        """
        Получить все остановки.
        """

        stops = repository.get_stops()

        return {
            "count": len(stops),
            "stops": stops,
        }

    # =========================================================
    # GET /api/stops/{stop_id}
    # =========================================================

    @router.get("/{stop_id}")
    def get_stop(
        stop_id: str,
    ):
        """
        Получить остановку.

        Например:

        /api/stops/3038
        """

        stops = repository.get_stop(
            stop_id
        )

        if not stops:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Остановка {stop_id} "
                    "не найдена"
                ),
            )

        return stops[0]

    return router