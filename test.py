def calcular_expresion(B, S, F, A, P):
    # Calcular división entera y resto de P/2
    division_entera = P // 2   # División entera
    resto_division = P % 2     # Resto de la división

    # Sumar el resto a A
    A += resto_division

    # Primer término: mínimo entre B y S
    termino1 = min(B, S)
    
    # Segundo término: mínimo entre |B–S| y F
    diff = abs(B - S)
    termino2 = min(diff, F)
    
    # Tercer término: round((F - min(diff, F)) / 2)
    resto = F - termino2
    termino3 = round(resto / 2)
    
    # Cuarto término: max(|B–S| - F, 0)
    termino4 = max(diff - F, 0)
    
    # Suma final con A y división entera
    return termino1 + termino2 + termino3 + termino4 + A + division_entera


def main():
    # Lectura de inputs desde consola
    B = float(input("Ingrese el valor de Pallets Base: "))
    S = float(input("Ingrese el valor de Pal Superior: "))
    F = float(input("Ingrese el valor de Pal Flexible: "))
    A = float(input("Ingrese el valor de Pal No Apilables: "))
    P = float(input("Ingrese el valor de Pal Apilables por si mismo: "))

    # Cálculo y presentación del resultado
    resultado = calcular_expresion(B, S, F, A, P)
    print(f"\nResultado: {resultado}")

if __name__ == "__main__":
    main()
