import type { ReferenceGeometryProperties, RouteDirection, RouteSegment, RouteStop } from "../api/types";

// Sparse, deterministic extract from dataset/spravochniki/Хакатон_справочники_трамвай_10_маршрутов.xlsx,
// sheet "Порядок_с_координатами". Source SHA-256:
// c6890032eee2aaa9ed1e252b1fe5c10c37a28c7bb5c1720a01a1409b1ff2bb71.
// Coordinates retain source order but are intentionally reduced for a lightweight UI fixture.
export const REFERENCE_VERSION = "sha256:c6890032eee2aaa9";

type StopTuple = [sequence: number, id: string, name: string, lat: number, lon: number];
interface FixturePath { route: number; routeId: string; tripId: string; directionId: number; validFrom: string; actualDate: string; stops: StopTuple[] }

const paths: FixturePath[] = [
  { route: 1, routeId: "4450", tripId: "2040920", directionId: 0, validFrom: "2025-10-11", actualDate: "2025-12-25", stops: [[1,"2594","Чертаново Южное",55.59468022,37.59088377],[2,"2595","Чертаново Южное",55.59657683,37.58807507],[8,"2599","Чертаново Центральное",55.61351128,37.59215968],[15,"2605","Верхний Чертановский пруд",55.63774302,37.60526029],[21,"2611","Болотниковская улица",55.65634537,37.60558607],[22,"2612","Москворецкий рынок",55.65841001,37.60862856]] },
  { route: 1, routeId: "4450", tripId: "2040921", directionId: 1, validFrom: "2025-10-11", actualDate: "2025-12-25", stops: [[1,"2612","Москворецкий рынок",55.65841001,37.60862856],[2,"2613","Болотниковская улица",55.65619014,37.60520769],[8,"2619","Верхний Чертановский пруд",55.63783765,37.60508089],[15,"2626","Чертаново Центральное",55.6117993,37.59149031],[21,"2628","Чертаново Южное",55.59667811,37.58788823],[22,"2594","Чертаново Южное",55.59468022,37.59088377]] },
  { route: 5, routeId: "3736", tripId: "2035712", directionId: 0, validFrom: "2025-12-16", actualDate: "2025-12-25", stops: [[1,"22101","Метро «Рижская»",55.79273918,37.63413048],[2,"22632","Улица Гиляровского",55.789966,37.63267531],[6,"1000594","МИИТ",55.78888604,37.61010557],[11,"16606","Улица Палиха",55.78482452,37.6006964],[15,"16612","Метро «Белорусская»",55.77726964,37.58648288],[16,"1001795","Белорусский вокзал",55.77634643,37.58343516]] },
  { route: 5, routeId: "3736", tripId: "2035713", directionId: 1, validFrom: "2025-12-16", actualDate: "2025-12-25", stops: [[1,"1001795","Белорусский вокзал",55.77634643,37.58343516],[2,"16614","Метро «Белорусская»",55.77714634,37.58669239],[6,"21549","Улица Палиха",55.78579101,37.60160559],[11,"22621","МИИТ",55.78904404,37.60980978],[15,"22633","Улица Гиляровского",55.79089476,37.63345573],[16,"22101","Метро «Рижская»",55.79273918,37.63413048]] },
  { route: 7, routeId: "4420", tripId: "2042578", directionId: 0, validFrom: "2025-12-20", actualDate: "2026-01-30", stops: [[1,"8605","Метро «Бульвар Рокоссовского»",55.81425897,37.73418276],[2,"8604","Метро «Бульвар Рокоссовского»",55.81522012,37.7329065],[16,"6242","Преображенская площадь",55.79524841,37.70927947],[31,"16514","Спорткомплекс «Олимпийский»",55.7807391,37.63235141],[44,"16612","Метро «Белорусская»",55.77726964,37.58648288],[45,"1001795","Белорусский вокзал",55.77634643,37.58343516]] },
  { route: 7, routeId: "4420", tripId: "2042579", directionId: 1, validFrom: "2025-12-20", actualDate: "2026-01-30", stops: [[1,"1001795","Белорусский вокзал",55.77634643,37.58343516],[2,"16614","Метро «Белорусская»",55.77714634,37.58669239],[15,"16515","Спорткомплекс «Олимпийский»",55.78055104,37.63249961],[30,"3703","Преображенская площадь",55.79516086,37.70936603],[43,"3692","5-й проезд Подбельского",55.81698697,37.72597918],[44,"8605","Метро «Бульвар Рокоссовского»",55.81425897,37.73418276]] },
  { route: 11, routeId: "4423", tripId: "2043371", directionId: 0, validFrom: "2025-12-20", actualDate: "2026-02-09", stops: [[1,"6152","Усадьба Останкино",55.8227811,37.61705787],[2,"6153","Усадьба Останкино",55.82346959,37.61571397],[15,"1001713","Богатырский мост",55.8167224,37.68907251],[29,"3624","Фортунатовская улица",55.78286096,37.73864919],[41,"3633","15-я Парковая улица",55.79350052,37.8198454],[42,"10463","Восточное Измайлово",55.79448147,37.82268714]] },
  { route: 11, routeId: "4423", tripId: "2043372", directionId: 1, validFrom: "2025-12-20", actualDate: "2026-02-09", stops: [[1,"10463","Восточное Измайлово",55.79448147,37.82268714],[2,"3707","Восточное Измайлово",55.79364821,37.82154062],[15,"3644","Фортунатовская улица",55.78309315,37.73908137],[29,"4531","Богородский храм",55.81493563,37.69426254],[42,"3659","Аргуновская улица",55.82192054,37.62187219],[43,"6152","Усадьба Останкино",55.8227811,37.61705787]] },
  { route: 12, routeId: "4428", tripId: "2043157", directionId: 0, validFrom: "2025-12-20", actualDate: "2026-02-05", stops: [[1,"10463","Восточное Измайлово",55.79448147,37.82268714],[2,"3707","Восточное Измайлово",55.79364821,37.82154062],[17,"3646","Метро «Семёновская»",55.78238945,37.72186995],[34,"15496","Старообрядческая улица",55.74786714,37.69482339],[49,"10737","МЦК Дубровка",55.71537983,37.67823797],[50,"8439","МЦК Дубровка",55.71421404,37.67850074]] },
  { route: 12, routeId: "4428", tripId: "2043158", directionId: 1, validFrom: "2025-12-20", actualDate: "2026-02-05", stops: [[1,"8439","МЦК Дубровка",55.71421404,37.67850074],[2,"8098","МЦК Дубровка",55.71521257,37.67853812],[16,"15495","Старообрядческая улица",55.74765675,37.69341695],[32,"3622","Метро «Семёновская»",55.78215255,37.72008527],[46,"3633","15-я Парковая улица",55.79350052,37.8198454],[47,"10463","Восточное Измайлово",55.79448147,37.82268714]] },
];

export const fixturePaths = paths.map((path) => {
  const geometryId = `ref-${path.route}-${path.tripId}-${path.directionId}-${path.validFrom}`;
  const properties: ReferenceGeometryProperties = { route: path.route, route_id: path.routeId, trip_id: path.tripId, direction_id: path.directionId, geometry_id: geometryId, valid_from: path.validFrom, valid_to: null, reference_actual_date: path.actualDate, geometry_source: "stop_sequence" };
  const direction: RouteDirection = { geometry_id: geometryId, trip_id: path.tripId, direction_id: path.directionId, valid_from: path.validFrom, valid_to: null };
  const stops: RouteStop[] = path.stops.map(([stop_sequence, stop_id, stop_name, lat, lon]) => ({ route: path.route, route_id: path.routeId, trip_id: path.tripId, direction_id: path.directionId, geometry_id: geometryId, stop_sequence, stop_id, stop_name, lat, lon }));
  const segments: RouteSegment[] = stops.slice(0, -1).flatMap((stop, index) => {
    const next = stops[index + 1];
    if (next.stop_sequence !== stop.stop_sequence + 1) return [];
    return [{ segment_id: `${geometryId}:${stop.stop_sequence}-${next.stop_sequence}`, geometry_id: geometryId, route: path.route, trip_id: path.tripId, direction_id: path.directionId, from_stop_id: stop.stop_id, to_stop_id: next.stop_id, from_sequence: stop.stop_sequence, to_sequence: next.stop_sequence, from_stop_name: stop.stop_name, to_stop_name: next.stop_name, geometry: { type: "LineString", coordinates: [[stop.lon, stop.lat], [next.lon, next.lat]] } }];
  });
  return { properties, direction, stops, segments, coordinates: stops.map((stop) => [stop.lon, stop.lat] as [number, number]) };
});
