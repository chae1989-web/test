import { useEffect, useState } from 'react'
import { getWeather, listKnownCities } from './api/weatherApi'
import './App.css'

const knownCities = listKnownCities()

function App() {
  const [query, setQuery] = useState('')
  const [weather, setWeather] = useState(null)
  const [status, setStatus] = useState('idle') // idle | loading | error
  const [error, setError] = useState('')

  function loadCity(city) {
    setStatus('loading')
    setError('')
    getWeather(city)
      .then((data) => {
        setWeather(data)
        setStatus('idle')
      })
      .catch((err) => {
        setWeather(null)
        setStatus('error')
        setError(err.message)
      })
  }

  useEffect(() => {
    loadCity(knownCities[0].name)
  }, [])

  function handleSubmit(e) {
    e.preventDefault()
    if (query.trim()) loadCity(query)
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>Weather App</h1>
        <form className="search" onSubmit={handleSubmit}>
          <input
            type="text"
            placeholder="도시 이름을 입력하세요 (예: Seoul)"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button type="submit">검색</button>
        </form>
        <div className="chips">
          {knownCities.map((city) => (
            <button
              key={city.id}
              className="chip"
              onClick={() => loadCity(city.name)}
            >
              {city.name}
            </button>
          ))}
        </div>
      </header>

      <main>
        {status === 'loading' && <p className="status">불러오는 중...</p>}
        {status === 'error' && <p className="status error">{error}</p>}

        {status === 'idle' && weather && (
          <>
            <section className="current-card">
              <div className="current-main">
                <span className="icon">{weather.icon}</span>
                <div>
                  <h2>
                    {weather.name}, {weather.country}
                  </h2>
                  <p className="condition">{weather.condition}</p>
                </div>
              </div>
              <div className="temp">{weather.temp}°C</div>
              <dl className="details">
                <div>
                  <dt>체감</dt>
                  <dd>{weather.feelsLike}°C</dd>
                </div>
                <div>
                  <dt>습도</dt>
                  <dd>{weather.humidity}%</dd>
                </div>
                <div>
                  <dt>바람</dt>
                  <dd>{weather.wind} km/h</dd>
                </div>
              </dl>
            </section>

            <section className="forecast">
              {weather.forecast.map((day) => (
                <div className="forecast-day" key={day.day}>
                  <p className="day">{day.day}</p>
                  <span className="icon">{day.icon}</span>
                  <p className="range">
                    {day.high}° / {day.low}°
                  </p>
                </div>
              ))}
            </section>
          </>
        )}
      </main>
    </div>
  )
}

export default App
