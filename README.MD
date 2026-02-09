# Entrar al enviroment
C:\venvs\backend-prod-env\Scripts\Activate.ps1

# Entrar a la carpeta backend
cd backend-prod

# Ejecutar backend
uvicorn app.main:app --port 8001

# Para levantarlo sin logs:
uvicorn app.main:app --no-access-log --port 8001

# Para ejecutar el frontend, debes encontrarte en la carpeta frontend-prod y es necesario tener un .env en la razís del front con lo siguiente:
VITE_API_BASE_URL=http://127.0.0.1:8001

# ejecutar
npm run dev
