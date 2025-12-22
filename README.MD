# Entrar al enviroment
C:\venvs\backend-prod-env\Scripts\Activate.ps1

# Entrar a la carpeta backend
cd backend-prod

# Ejecutar backend
uvicorn app.main:app --port 8001

# Para levantarlo sin logs:
uvicorn app.main:app --access-log false --port 8001


# Para ejecutar el forntend, debes encontrarte en la carpeta frontend-prod y ejecutar
npm run dev