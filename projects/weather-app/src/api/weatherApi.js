import { mockWeather } from '../data/mockWeather'

const SIMULATED_DELAY_MS = 400

function normalize(query) {
  return query.trim().toLowerCase().replace(/\s+/g, '-')
}

// Currently serves data from src/data/mockWeather.js. To switch to a real
// provider (e.g. OpenWeatherMap), replace the body below with a fetch call:
//
//   const res = await fetch(
//     `https://api.openweathermap.org/data/2.5/weather?q=${city}&units=metric&appid=${import.meta.env.VITE_WEATHER_API_KEY}`
//   )
//   if (!res.ok) throw new Error('City not found')
//   return res.json()
//
// Keep the function signature (city string in, weather object out) so the
// rest of the app doesn't need to change.
export async function getWeather(city) {
  await new Promise((resolve) => setTimeout(resolve, SIMULATED_DELAY_MS))

  const entry = mockWeather[normalize(city)]
  if (!entry) {
    throw new Error(`"${city}"의 날씨 정보를 찾을 수 없어요.`)
  }
  return entry
}

export function listKnownCities() {
  return Object.values(mockWeather).map(({ id, name, country }) => ({ id, name, country }))
}
