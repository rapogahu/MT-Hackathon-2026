from fastapi import APIRouter


router = APIRouter(
    prefix="/api/stops",
    tags=["Stops"]
)


STOPS = [
    {
        "id": "21",
        "name": "Остановка 21",
        "latitude": 55.751,
        "longitude": 37.615,
        "routes": ["3"]
    },
    {
        "id": "16",
        "name": "Остановка 16",
        "latitude": 55.753,
        "longitude": 37.621,
        "routes": ["3"]
    },
    {
        "id": "17",
        "name": "Остановка 17",
        "latitude": 55.755,
        "longitude": 37.628,
        "routes": ["7"]
    },
    {
        "id": "201",
        "name": "Остановка 201",
        "latitude": 55.760,
        "longitude": 37.610,
        "routes": ["21"]
    }
]


@router.get("/")
def get_stops(route_id: str | None = None):

    if route_id is None:
        return STOPS

    return [
        stop
        for stop in STOPS
        if route_id in stop["routes"]
    ]