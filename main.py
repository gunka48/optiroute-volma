import math
import json
import urllib.request
import webbrowser
import threading
import time
from typing import List, Dict, Any
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

app = FastAPI(title="OptiRoute VOLMA Engine")

# =====================================================================
# 1. ИНФРАСТРУКТУРА УК «ВОЛМА» (4 Карьера, 9 Заводов, 1 Хаб)
# =====================================================================
VOLMA_NODES = [
    {"id": 0, "name": "ВОЛМА-Волгоград (Головной хаб)", "lat": 48.7194, "lon": 44.5018, "type": "plant"},
    {"id": 1, "name": "Карьер Дубенский (Оренбург)", "lat": 51.5361, "lon": 55.4512, "type": "quarry"},
    {"id": 2, "name": "Карьер Псебайский (Адыгея)", "lat": 44.1235, "lon": 40.6412, "type": "quarry"},
    {"id": 3, "name": "Карьер Баскунчак (Астрахань)", "lat": 48.2167, "lon": 46.8833, "type": "quarry"},
    {"id": 4, "name": "Карьер Самарская Лука", "lat": 53.4167, "lon": 50.0167, "type": "quarry"},
    {"id": 5, "name": "ВОЛМА-ВТР (Волгоград)", "lat": 48.7650, "lon": 44.4820, "type": "plant"},
    {"id": 6, "name": "ВОЛМА-Воскресенск (Московская обл.)", "lat": 55.3225, "lon": 38.6836, "type": "plant"},
    {"id": 7, "name": "ВОЛМА-Оренбург", "lat": 51.7681, "lon": 55.0969, "type": "plant"},
    {"id": 8, "name": "ВОЛМА-Челябинск", "lat": 55.1644, "lon": 61.4368, "type": "plant"},
    {"id": 9, "name": "ВОЛМА-Майкоп (Адыгея)", "lat": 44.6098, "lon": 40.1006, "type": "plant"},
    {"id": 10, "name": "ВОЛМА-Абсалямово (Татарстан)", "lat": 54.5828, "lon": 53.4756, "type": "plant"},
    {"id": 11, "name": "ВОЛМА-Иркутск (Шелехов)", "lat": 52.2039, "lon": 104.0958, "type": "plant"},
    {"id": 12, "name": "ВОЛМА-Караганда (Казахстан)", "lat": 49.8019, "lon": 73.1021, "type": "plant"},
]

@app.get("/api/all-nodes")
def get_all_nodes():
    return VOLMA_NODES

# Промежуточные узлы для создания физической разницы маршрутов (Федеральная трасса vs Региональная срезка)
SHORTCUT_WAYPOINTS = {
    (0, 6): {"lat": 52.7236, "lon": 41.4423},  # Волгоград -> Воскресенск через Тамбов (регионалка)
    (1, 8): {"lat": 53.2000, "lon": 59.0000},  # Карьер Дубенский -> Челябинск (регионалка)
}

# =====================================================================
# 2. ПОСТРОЕНИЕ ТРАСС (OSRM ROUTING)
# =====================================================================
def get_real_road_path(start_lat, start_lon, end_lat, end_lon, via_point=None):
    if via_point:
        url = f"http://router.project-osrm.org/route/v1/driving/{start_lon},{start_lat};{via_point['lon']},{via_point['lat']};{end_lon},{end_lat}?overview=full&geometries=geojson"
    else:
        url = f"http://router.project-osrm.org/route/v1/driving/{start_lon},{start_lat};{end_lon},{end_lat}?overview=full&geometries=geojson"
        
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'OptiRouteVOLMA/1.0'})
        with urllib.request.urlopen(req, timeout=4) as response:
            data = json.loads(response.read().decode())
            if data.get("routes"):
                route = data["routes"][0]
                dist_km = route["distance"] / 1000.0
                path_coords = [[pt[1], pt[0]] for pt in route["geometry"]["coordinates"]]
                return dist_km, path_coords
    except Exception:
        pass
    
    # Геодезический резерв
    R = 6371.0
    dlat, dlon = math.radians(end_lat - start_lat), math.radians(end_lon - start_lon)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(start_lat)) * math.cos(math.radians(end_lat)) * math.sin(dlon/2)**2
    dist_km = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a)) * R * 1.25
    return dist_km, [[start_lat, start_lon], [end_lat, end_lon]]

# =====================================================================
# 3. БИЗНЕС-ЛОГИКА: РЕЖИМ ТРУДА И ОТДЫХА (ЕСТР / МИНТРАНС РФ)
# =====================================================================
class CalculateRouteRequest(BaseModel):
    from_node_id: int
    to_node_id: int
    cargo_type: str 
    use_road_quality: bool

@app.post("/api/calculate-route")
def calculate_route(req: CalculateRouteRequest):
    nodes = {n["id"]: n for n in VOLMA_NODES}
    n1 = nodes[req.from_node_id]
    n2 = nodes[req.to_node_id]

    # Если качество дорог ОТКЛЮЧЕНО — заставляем роутер идти по региональной срезке
    via_pt = None
    if not req.use_road_quality:
        via_pt = SHORTCUT_WAYPOINTS.get((req.from_node_id, req.to_node_id)) or SHORTCUT_WAYPOINTS.get((req.to_node_id, req.from_node_id))

    dist_km, road_path = get_real_road_path(n1["lat"], n1["lon"], n2["lat"], n2["lon"], via_point=via_pt)

    # --- Точный расчет Минтранса РФ (ЕСТР) ---
    avg_speed = 75.0  # Средняя скорость тяжелой фуры на трассе (км/ч)
    pure_driving_hours = dist_km / avg_speed

    # 1. Короткие перерывы (45 мин) каждые 4.5 часа езды
    short_breaks_count = int(pure_driving_hours // 4.5)
    
    # 2. Суточный отдых (11 часов) после 9 часов руления
    long_rests_count = int(pure_driving_hours // 9.0)
    
    # Исключаем наложение короткого перерыва на ночной сон
    if short_breaks_count > 0 and long_rests_count > 0:
        short_breaks_count -= long_rests_count

    total_break_hours = (short_breaks_count * 0.75) + (long_rests_count * 11.0)
    total_trip_hours = pure_driving_hours + total_break_hours

    days = int(total_trip_hours // 24)
    hours = int(total_trip_hours % 24)
    mins = int((total_trip_hours * 60) % 60)

    time_str = f"{days} дн {hours} ч {mins} мин" if days > 0 else f"{hours} ч {mins} мин"

    # Экономика и повреждения
    base_tariff_per_km = 70.0 
    transport_cost = dist_km * base_tariff_per_km
    fragility_risk_pct = 0.0
    cargo_damage_cost = 0.0
    cargo_name, road_recommendation = "", ""

    if req.cargo_type == "stone":
        cargo_name = "Гипсовый камень (Сырье)"
        fragility_risk_pct = 0.0
        cargo_damage_cost = 0.0
        road_recommendation = "Сырье не чувствительно к тряске. Выбран кратчайший путь."
    elif req.cargo_type == "gkl":
        cargo_name = "Гипсокартон (ГКЛ / ПГП)"
        if req.use_road_quality:
            fragility_risk_pct = 1.2
            cargo_damage_cost = dist_km * 8.0
            road_recommendation = "✅ ОПТИМАЛЬНО: Трасса проложена по федеральным магистралям высокой категории. Минимальный риск боя."
        else:
            fragility_risk_pct = 13.4
            cargo_damage_cost = dist_km * 125.0
            road_recommendation = "🚨 КРИТИЧЕСКИЙ БОЙ: Путь пролегает по разбитым региональным дорогам! Убыток от боя превысит 13% от стоимости груза."
    else:
        cargo_name = "Сухие строительные смеси"
        fragility_risk_pct = 2.0 if req.use_road_quality else 6.5
        cargo_damage_cost = dist_km * 18.0 if not req.use_road_quality else dist_km * 3.5
        road_recommendation = "Перевозка в паллетах. Желательно использовать федеральные трассы."

    return {
        "status": "success",
        "cargo_name": cargo_name,
        "from_node": n1["name"],
        "to_node": n2["name"],
        "distance_km": round(dist_km, 1),
        "pure_driving_hours": round(pure_driving_hours, 1),
        "time_str": time_str,
        "short_breaks": short_breaks_count,
        "long_rests": long_rests_count,
        "transport_cost_rub": round(transport_cost, 0),
        "cargo_damage_risk_pct": fragility_risk_pct,
        "damage_cost_rub": round(cargo_damage_cost, 0),
        "road_recommendation": road_recommendation,
        "path_geometry": road_path
    }

# =====================================================================
# 4. ИНТЕРФЕЙС
# =====================================================================
@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>OptiRoute ВОЛМА | Хакатон ТЕХНОВЕКтор 20.26</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        .leaflet-control-attribution { display: none !important; }
        #map { height: calc(100vh - 64px); background-color: #0f172a; }
    </style>
</head>
<body class="bg-slate-900 text-slate-100 font-sans flex flex-col h-screen overflow-hidden">

    <!-- ХЕДЕР -->
    <header class="h-16 bg-slate-800 border-b border-slate-700 px-6 flex items-center justify-between shrink-0">
        <div class="flex items-center space-x-4">
            <div class="bg-emerald-500 text-slate-950 px-3 py-1.5 rounded-xl font-bold flex items-center shadow-lg">
                <i class="fa-solid fa-route text-xl mr-2"></i>
                <span class="text-lg font-black tracking-tight">OptiRoute <span class="text-white">ВОЛМА</span></span>
            </div>
            
            <span class="text-[10px] bg-red-500/20 text-red-400 px-3 py-1.5 rounded-full border border-red-500/50 font-bold uppercase tracking-widest shadow-lg">
                <i class="fa-solid fa-triangle-exclamation mr-1"></i> DEMO-ВЕРСИЯ (MVP)
            </span>
        </div>

        <div class="text-xs text-slate-400 font-mono hidden md:block">
            Хакатон «ТЕХНОВЕКтор 20.26» • Кейс ВОЛМА
        </div>
    </header>

    <!-- ОСНОВНАЯ ОБЛАСТЬ -->
    <div class="flex flex-1 overflow-hidden relative">
        
        <!-- ЛЕВАЯ ПАНЕЛЬ -->
        <div class="w-[420px] bg-slate-800/95 border-r border-slate-700 flex flex-col h-full z-10 p-4 space-y-4 shadow-2xl overflow-y-auto">
            
            <!-- КНОПКА ПОКАЗАТЬ ВСЕ -->
            <button onclick="showAllNodes()" class="w-full bg-blue-600 hover:bg-blue-500 text-white py-2.5 rounded-xl text-xs font-bold transition shadow-lg flex items-center justify-center">
                <i class="fa-solid fa-map-location-dot mr-2"></i> Отобразить все объекты ВОЛМА
            </button>

            <!-- КОНСТРУКТОР МАРШРУТА -->
            <div class="bg-slate-900/90 p-4 rounded-2xl border border-slate-700/80 space-y-3 shadow-inner">
                <div class="text-xs font-bold text-emerald-400 uppercase tracking-wider flex items-center">
                    <i class="fa-solid fa-sliders mr-2"></i> Параметры рейса
                </div>

                <div>
                    <label class="block text-[11px] text-slate-400 mb-1 font-semibold">1. Отправление (Точка А):</label>
                    <select id="selectFrom" class="w-full bg-slate-800 border border-slate-600 p-2 rounded-xl text-xs text-slate-200">
                        <option value="0" selected>ВОЛМА-Волгоград (Головной хаб)</option>
                        <option value="1">Карьер Дубенский (Оренбург)</option>
                        <option value="2">Карьер Псебайский (Адыгея)</option>
                        <option value="3">Карьер Баскунчак (Астрахань)</option>
                        <option value="4">Карьер Самарская Лука</option>
                    </select>
                </div>

                <div>
                    <label class="block text-[11px] text-slate-400 mb-1 font-semibold">2. Назначение (Точка Б):</label>
                    <select id="selectTo" class="w-full bg-slate-800 border border-slate-600 p-2 rounded-xl text-xs text-slate-200">
                        <option value="6" selected>ВОЛМА-Воскресенск (Московская обл.)</option>
                        <option value="7">ВОЛМА-Оренбург</option>
                        <option value="8">ВОЛМА-Челябинск</option>
                        <option value="9">ВОЛМА-Майкоп (Адыгея)</option>
                        <option value="11">ВОЛМА-Иркутск (Шелехов)</option>
                        <option value="12">ВОЛМА-Караганда (Казахстан)</option>
                    </select>
                </div>

                <div>
                    <label class="block text-[11px] text-slate-400 mb-1 font-semibold">3. Тип перевозимого груза:</label>
                    <select id="selectCargo" onchange="toggleCargoHint()" class="w-full bg-slate-800 border border-slate-600 p-2 rounded-xl text-xs text-slate-200 font-bold text-amber-400">
                        <option value="gkl">ХРУПКИЙ: Гипсокартон (ГКЛ / ПГП)</option>
                        <option value="stone">СЫРЬЕ: Гипсовый камень (Не бьется)</option>
                        <option value="mix">СМЕСИ: Сухие строительные смеси</option>
                    </select>
                </div>

                <div class="pt-1">
                    <label class="flex items-center justify-between cursor-pointer text-xs bg-slate-800 p-2.5 rounded-xl border border-slate-700">
                        <span class="text-slate-200 font-medium"><i class="fa-solid fa-road text-amber-400 mr-1.5"></i>Учет качества трасс</span>
                        <input type="checkbox" id="checkRoad" checked class="w-4 h-4 text-emerald-500 rounded bg-slate-700 border-slate-600">
                    </label>
                </div>

                <button onclick="buildUserRoute()" class="w-full bg-emerald-600 hover:bg-emerald-500 text-white py-2.5 rounded-xl text-xs font-bold transition shadow-lg flex items-center justify-center">
                    <i class="fa-solid fa-route mr-2"></i> Рассчитать маршрут
                </button>
            </div>

            <!-- РЕЗУЛЬТАТ РАСЧЕТА -->
            <div id="resultCard" class="hidden bg-slate-900/90 p-4 rounded-2xl border border-slate-700/80 space-y-3">
                <div class="text-xs font-bold text-slate-400 uppercase tracking-wider flex items-center justify-between border-b border-slate-700 pb-2">
                    <span>Сводка по маршруту</span>
                    <span id="cargoBadge" class="text-[10px] bg-amber-500/20 text-amber-400 px-2 py-0.5 rounded-full font-bold">ГКЛ</span>
                </div>

                <!-- Блок времени и расстояния -->
                <div class="grid grid-cols-2 gap-2">
                    <div class="bg-slate-800/60 p-2.5 rounded-xl border border-slate-700">
                        <div class="text-[10px] text-slate-400">Дистанция</div>
                        <div id="resDist" class="text-sm font-black text-white mt-0.5">0 км</div>
                    </div>
                    <div class="bg-slate-800/60 p-2.5 rounded-xl border border-slate-700">
                        <div class="text-[10px] text-slate-400">Стоимость фрахта</div>
                        <div id="resCost" class="text-sm font-black text-emerald-400 mt-0.5">0 ₽</div>
                    </div>
                </div>

                <!-- Детализация времени по правилам ЕСТР -->
                <div class="bg-slate-800/60 p-2.5 rounded-xl border border-slate-700 space-y-1.5">
                    <div class="text-[10px] font-bold uppercase text-slate-400 border-b border-slate-700/50 pb-1">
                        <i class="fa-solid fa-clock text-emerald-400 mr-1"></i> Режим труда водителя (ЕСТР)
                    </div>
                    <div class="flex justify-between text-[11px]">
                        <span class="text-slate-400">Чистая езда (75 км/ч):</span>
                        <span id="resDrivingTime" class="font-bold text-slate-200">0 ч</span>
                    </div>
                    <div class="flex justify-between text-[11px]">
                        <span class="text-slate-400">Перерывы (по 45 мин):</span>
                        <span id="resShortBreaks" class="font-bold text-amber-400">0 остановок</span>
                    </div>
                    <div class="flex justify-between text-[11px]">
                        <span class="text-slate-400">Ночевки / Сон (по 11 ч):</span>
                        <span id="resLongRests" class="font-bold text-amber-400">0 ночевок</span>
                    </div>
                    <div class="flex justify-between text-[11px] pt-1 border-t border-slate-700/50">
                        <span class="text-slate-300 font-bold">Общее время рейса:</span>
                        <span id="resTotalTime" class="font-black text-emerald-400">0 ч</span>
                    </div>
                </div>

                <!-- Блок убытков от боя -->
                <div class="bg-slate-800/60 p-2.5 rounded-xl border border-slate-700 space-y-1">
                    <div class="flex justify-between text-[11px]">
                        <span class="text-slate-400">Риск боя продукции:</span>
                        <span id="resRisk" class="font-bold text-cyan-400">0%</span>
                    </div>
                    <div class="flex justify-between text-[11px]">
                        <span class="text-slate-400">Убыток от тряски:</span>
                        <span id="resDamage" class="font-bold text-red-400">0 ₽</span>
                    </div>
                </div>

                <div class="text-[11px] text-slate-300 bg-slate-800/80 p-2.5 rounded-xl border border-slate-700 italic leading-relaxed" id="resHint"></div>
            </div>

        </div>

        <!-- КАРТА LEAFLET -->
        <div class="flex-1 relative">
            <div id="map"></div>
            
            <div class="absolute bottom-6 right-6 bg-slate-900/90 backdrop-blur border border-slate-700 p-3.5 rounded-xl shadow-2xl z-[1000] text-xs space-y-2">
                <div class="font-bold text-slate-200 border-b border-slate-700 pb-1 flex items-center">
                    <i class="fa-solid fa-layer-group text-emerald-400 mr-2"></i> Инфраструктура ВОЛМА
                </div>
                <div class="flex items-center"><span class="w-3 h-3 rounded-full bg-amber-500 mr-2 shadow"></span> 4 Месторождения (Сырье)</div>
                <div class="flex items-center"><span class="w-3 h-3 rounded-full bg-blue-500 mr-2 shadow"></span> 9 Заводов ВОЛМА</div>
                <div class="flex items-center"><span class="w-3 h-3 rounded-full bg-emerald-500 mr-2 shadow"></span> Головной хаб (Волгоград)</div>
            </div>
        </div>

    </div>

    <!-- СКРИПТ КАРТЫ И API -->
    <script>
        var map = L.map('map', { zoomControl: false, attributionControl: false }).setView([52.0, 50.0], 5);
        L.control.zoom({ position: 'topright' }).addTo(map);

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18 }).addTo(map);

        var activeLayers = [];

        // Функция: Отображение ВСЕХ объектов ВОЛМА
        async function showAllNodes() {
            const res = await fetch('/api/all-nodes');
            const nodes = await res.json();

            // Очистка карты
            activeLayers.forEach(l => map.removeLayer(l));
            activeLayers = [];
            document.getElementById('resultCard').classList.add('hidden');

            const bounds = [];
            nodes.forEach(n => {
                let color = '#3b82f6';
                if (n.type === 'quarry') color = '#f59e0b';
                if (n.id === 0) color = '#10b981';

                const m = L.circleMarker([n.lat, n.lon], {
                    radius: 8, color: '#ffffff', weight: 2, fillOpacity: 1, fillColor: color
                }).bindPopup(`<b>${n.name}</b><br>Тип: ${n.type === 'quarry' ? 'Месторождение гипса' : 'Площадка ВОЛМА'}`).addTo(map);
                
                activeLayers.push(m);
                bounds.push([n.lat, n.lon]);
            });

            map.fitBounds(bounds, {padding: [50, 50]});
        }

        async function buildUserRoute() {
            const fromId = parseInt(document.getElementById('selectFrom').value);
            const toId = parseInt(document.getElementById('selectTo').value);
            const cargo = document.getElementById('selectCargo').value;
            const useRoad = document.getElementById('checkRoad').checked;

            if (fromId === toId) return alert('Точки отправления и назначения не могут совпадать!');

            const res = await fetch('/api/calculate-route', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({from_node_id: fromId, to_node_id: toId, cargo_type: cargo, use_road_quality: useRoad})
            });

            displayRouteResult(await res.json());
        }

        function displayRouteResult(data) {
            document.getElementById('resultCard').classList.remove('hidden');
            activeLayers.forEach(l => map.removeLayer(l));
            activeLayers = [];

            // UI
            document.getElementById('resDist').innerText = data.distance_km + ' км';
            document.getElementById('resCost').innerText = data.transport_cost_rub.toLocaleString('ru-RU') + ' ₽';
            document.getElementById('resDrivingTime').innerText = data.pure_driving_hours + ' ч';
            document.getElementById('resShortBreaks').innerText = data.short_breaks + ' (по 45 мин)';
            document.getElementById('resLongRests').innerText = data.long_rests + ' (по 11 ч)';
            document.getElementById('resTotalTime').innerText = data.time_str;

            document.getElementById('resRisk').innerText = data.cargo_damage_risk_pct + '%';
            document.getElementById('resDamage').innerText = data.damage_cost_rub.toLocaleString('ru-RU') + ' ₽';
            document.getElementById('resHint').innerHTML = data.road_recommendation;
            document.getElementById('cargoBadge').innerText = data.cargo_name.split(' ')[0];

            // Отрисовка трассы
            const isDanger = data.cargo_damage_risk_pct > 5;
            const polyline = L.polyline(data.path_geometry, { 
                color: isDanger ? '#ef4444' : '#10b981', 
                weight: 6,
                opacity: 0.9
            }).addTo(map);
            activeLayers.push(polyline);

            // Иконка грузовика
            const midPt = data.path_geometry[Math.floor(data.path_geometry.length / 2)];
            const truckIcon = L.divIcon({
                className: 'custom-truck',
                html: `<div style="background-color:${isDanger ? '#ef4444' : '#10b981'}; width:34px; height:32px; border-radius:8px; display:flex; align-items:center; justify-content:center; color:white; border:2px solid white; font-size:15px; box-shadow: 0 4px 10px rgba(0,0,0,0.5);"><i class="fa-solid fa-truck"></i></div>`,
                iconSize: [34, 32], iconAnchor: [17, 16]
            });

            const truckMarker = L.marker(midPt, {icon: truckIcon}).bindPopup(`<b>Рейс ВОЛМА</b><br>Груз: ${data.cargo_name}<br>Плечо: ${data.distance_km} км`).addTo(map);
            activeLayers.push(truckMarker);

            // Точки А и Б
            activeLayers.push(L.circleMarker(data.path_geometry[0], {radius: 9, fillColor: '#f59e0b', color: '#fff', weight: 2, fillOpacity: 1}).bindPopup('<b>Точка А:</b> ' + data.from_node).addTo(map));
            activeLayers.push(L.circleMarker(data.path_geometry[data.path_geometry.length-1], {radius: 9, fillColor: '#3b82f6', color: '#fff', weight: 2, fillOpacity: 1}).bindPopup('<b>Точка Б:</b> ' + data.to_node).addTo(map));

            map.fitBounds(polyline.getBounds(), {padding: [50, 50]});
        }

        function toggleCargoHint() {
            document.getElementById('checkRoad').checked = document.getElementById('selectCargo').value !== 'stone';
        }

        window.onload = () => { showAllNodes(); };
    </script>
</body>
</html>
    """

def open_browser():
    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:8000")

if __name__ == "__main__":
    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8000)