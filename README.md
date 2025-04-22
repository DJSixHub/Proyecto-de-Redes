# Proyecto de Evaluación: Chat Descentralizado en LAN

**Curso:** Ciencias de la Computación - Sistemas Computacionales y Redes  
**Objetivo:** Implementar un chat descentralizado que funcione en una red local (LAN) siguiendo el protocolo especificado en [`lcp_protocol.md`](lcp_protocol.md).  

## Requisitos Básicos (3 puntos)  
1. **Cumplir con el protocolo LCP:** La solución debe seguir estrictamente la especificación del protocolo.  
2. **Autodescubrimiento de vecinos:** No se debe requerir que los usuarios ingresen direcciones manualmente. La solución debe detectar automáticamente otros clientes en la misma LAN.  

## Puntos Adicionales  

### 1. Mensajería Uno-a-Muchos (0.25 pts)  
- Enviar un mensaje a todos los vecinos con una única transmisión, no enviando copias individuales.  

### 2. Manejo de Mensajes Simultáneos (0.25 pts)  
- La solución debe procesar múltiples mensajes concurrentemente sin bloquear la ejecución.  

### 3. Mensajes Grupales (0.75 pts)  
- Extender el protocolo para soportar:  
  - Creación/suscripción a grupos.  
  - Envío/recepción de mensajes grupales.  

### 4. Recuperación de Historial (0.75 pts)  
- Al reconectarse, un usuario debe poder recuperar los últimos 10 mensajes intercambiados con cada vecino (excluyendo archivos).  

### 5. Interfaz Gráfica (Hasta 1 pt)  
- **Básica (0.5 pts):** Interfaz funcional con listado de usuarios y área de mensajes.  
- **Avanzada (0.5 pts adicionales):**  
  - Diseño intuitivo y detallado (ej: pestañas para grupos).  
  - Sin bloqueos y/o esperas durante operaciones de red.  

## Fecha de Entrega  
**19 de mayo, 11:59:59 PM**  
- Entregar mediante **Issue o Pull Request** al presente repositorio.
