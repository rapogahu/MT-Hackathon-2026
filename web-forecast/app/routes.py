from fastapi import APIRouter


router = APIRouter(
    prefix="/api/routes",
    tags=["Routes"]
)


ROUTES = [
    {
        "id": "3",
        "name": "Трамвай 3"
    },
    {
        "id": "7",
        "name": "Трамвай 7"
    },
    {
        "id": "21",
        "name": "Трамвай 21"
    }
]


@router.get("/")
def get_routes():
    return ROUTES