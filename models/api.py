from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional


class PostProcessRequest(BaseModel):
    camiones: List[Dict[str, Any]] = Field(default_factory=list)
    pedidos_no_incluidos: List[Dict[str, Any]] = Field(default_factory=list)
    pedidos: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    target_truck_id: Optional[str] = None
    cd: Optional[List[str]] = Field(default_factory=list)
    ce: Optional[List[str]] = Field(default_factory=list)
    ruta: Optional[str] = None
    cliente: str
    venta: Optional[str] = None


class PostProcessResponse(BaseModel):
    camiones: List[Dict[str, Any]]
    pedidos_no_incluidos: List[Dict[str, Any]]
    estadisticas: Dict[str, Any]

