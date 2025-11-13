# Entrar al enviroment
C:\venvs\backend-prod-env\Scripts\Activate.ps1

# Entrar a la carpeta backend
cd backend-prod

# Ejecutar backend
uvicorn app.main:app --port 8001


# Para ejecutar el forntend, debes esncontrarte en la carpeta frontend-prod y ejecutar
np run dev