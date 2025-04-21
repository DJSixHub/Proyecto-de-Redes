# **Local Chat Protocol (LCP) Specification**  
**Version:** 1.0  
**Ports:** UDP/9990 (control), TCP/9990 (file transfer)  

---

## **1. Overview**  
The **Local Chat Protocol (LCP)** is a lightweight protocol designed for peer-to-peer messaging and file transfers within a Local Area Network (LAN). It operates over **UDP (control messages)** and **TCP (file transfers)** on port **9990**.  

LCP defines three fundamental operations:  
- **Echo-Reply (0)** – User discovery  
- **Message-Response (1)** – Text messaging  
- **Send File-Ack (2)** – File transfers  

---

## **2. Packet Structure**  

### **2.1. Header (Fixed: 100 bytes)**  
All operations begin with this header (UDP).  

| Field          | Size (bytes) | Description |
|----------------|--------------|-------------|
| `UserIdFrom`   | 20           | Sender’s unique identifier (UTF-8). |
| `UserIdTo`     | 20           | Recipient’s ID (all `0xFF` = broadcast). |
| `OperationCode`| 1            | `0` (Echo), `1` (Message), `2` (File). |
| `BodyId`       | 1 (optional) | Unique ID for multi-part messages. |
| `BodyLength`   | 8 (optional) | Size of the body (in bytes). |
| **Reserved**   | 50           | Reserved for future use. |

---

### **2.2. Response (Fixed: 25 bytes)**  
Sent after processing a request.  

| Field            | Size (bytes) | Description |
|------------------|--------------|-------------|
| `ResponseStatus` | 1            | `0`=OK, `1`=Bad Request, `2`=Internal Error. |
| `ResponseId`     | 20 (optional)| Responder’s UserId. |
| **Reserved**     | 4            | Reserved for future use. |

---

## **3. Operations**  

### **3.1. Operation 0: Echo-Reply (Discovery)**  
**Purpose:** Discover users in the LAN.  
**Protocol:** UDP only.  

#### **Request (A → Discovery)**  
- `UserIdFrom` = Sender’s ID  
- `UserIdTo` = `0xFF...FF`   
- `OperationCode` = `0`  
- Rest of header **ignored**.  

#### **Response (B → A)**  
- `ResponseStatus` = `0` (OK)  
- `ResponseId` = B’s UserId  

---

### **3.2. Operation 1: Message-Response (Text Chat)**  
**Purpose:** Send a text message.  
**Protocol:** UDP only.  

#### **Phase 1: Header (A → B)**  
- `UserIdFrom` = A’s ID  
- `UserIdTo` = B’s ID  
- `OperationCode` = `1`  
- `BodyId` = Unique message ID  
- `BodyLength` = Message size  

#### **Phase 2: Body (A → B, only if `ResponseStatus=0`)**  
- First **8 bytes**: Message ID (matching `BodyId`)  
- Remaining bytes: Message content (UTF-8).  

#### **Final Response (B → A)**  
- `ResponseStatus` = `0` (OK) if received correctly.  

---

### **3.3. Operation 2: Send File-Ack (File Transfer)**  
**Purpose:** Send a file.  
**Protocol:** UDP (header) + TCP (data).  

#### **Phase 1: Header (A → B, UDP)**  
- `UserIdFrom` = A’s ID  
- `UserIdTo` = B’s ID  
- `OperationCode` = `2`  
- `BodyId` = Unique file ID  
- `BodyLength` = File size  

#### **Phase 2: File Data (A → B, TCP)**  
- First **8 bytes**: File ID (matching `BodyId`)  
- Remaining bytes: File content (raw binary).  

#### **Final Response (B → A, TCP)**  
- `ResponseStatus` = `0` (OK) if file received correctly.  

---

## **4. Error Handling**  
- If `ResponseStatus != 0`, the sender should retry or abort.  
- Timeout: If no response after **5 seconds**, consider the operation failed.  

---

## **5. Security Considerations**  
- **No encryption**: LCP is designed for LAN use only.  
- **No authentication**: Trust is assumed within the local network.  

---

## **6. Example Workflows**  

### **6.1. User Discovery**  
1. **A** broadcasts `Echo` (`Operation=0`).  
2. **B** replies with `ResponseId`.  

### **6.2. Sending a Message**  
1. **A** sends header (`Operation=1`).  
2. **B** responds `OK`.  
3. **A** sends message body.  
4. **B** confirms receipt.  

### **6.3. Sending a File**  
1. **A** sends header (`Operation=2`) via UDP.  
2. **B** responds `OK`.  
3. **A** sends file via TCP.  
4. **B** confirms receipt via TCP.  

---

This specification defines **LCP v1.0**. Implementations must adhere to the described formats for interoperability.  