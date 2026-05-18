import time
import requests
from config import Config

BASE_URL = "https://api.hydradb.com"

def get_headers():
    """Returns headers with authorization token and content-type."""
    return {
        "Authorization": f"Bearer {Config.HYDRADB_API_KEY}",
        "Content-Type": "application/json"
    }

def create_tenant(tenant_id: str) -> bool:
    """
    POST /tenants/create with {"tenant_id": tenant_id}
    Poll GET /tenants/infra/status?tenant_id={tenant_id} every 2 seconds 
    until status is "ready" (max 30 seconds)
    Return True on success, False on failure
    """
    if not Config.HYDRADB_API_KEY:
        print("Error: HYDRADB_API_KEY is not set.")
        return False
        
    create_url = f"{BASE_URL}/tenants/create"
    payload = {"tenant_id": tenant_id}
    
    try:
        # Create tenant request
        response = requests.post(create_url, json=payload, headers=get_headers(), timeout=10)
        # Even if create response is not ok (e.g. 409 Conflict if tenant already exists),
        # we will still try to poll status, as it might already be ready.
        if not response.ok:
            print(f"HydraDB tenants/create status code {response.status_code}: {response.text}")
            
        status_url = f"{BASE_URL}/tenants/infra/status"
        start_time = time.time()
        
        # Poll status for max 30 seconds
        while time.time() - start_time < 30:
            try:
                status_resp = requests.get(
                    status_url, 
                    params={"tenant_id": tenant_id}, 
                    headers=get_headers(), 
                    timeout=5
                )
                if status_resp.ok:
                    data = status_resp.json()
                    
                    # Extract status check from nested data or directly
                    status = data.get("status")
                    if not status and "data" in data and isinstance(data["data"], dict):
                        status = data["data"].get("status")
                        
                    if status == "ready":
                        print(f"HydraDB Tenant {tenant_id} infrastructure is READY.")
                        return True
                    else:
                        print(f"HydraDB Tenant {tenant_id} status: {status}. Retrying...")
                else:
                    print(f"HydraDB status poll HTTP {status_resp.status_code}: {status_resp.text}")
            except Exception as poll_e:
                print(f"HydraDB status poll exception: {poll_e}")
                
            time.sleep(2)
            
        print(f"HydraDB Tenant {tenant_id} infrastructure failed to become ready in 30 seconds.")
        return False
    except Exception as e:
        print(f"HydraDB create_tenant exception: {e}")
        return False

def store_memory(tenant_id: str, transcript: str, title: str) -> bool:
    """
    POST /memories/add_memory with:
    {
      "tenant_id": tenant_id,
      "sub_tenant_id": "main",
      "memories": [
        {"text": transcript, "infer": true},
        {"text": "Video title: {title}", "infer": false}
      ]
    }
    Return True on success, False on failure
    """
    if not Config.HYDRADB_API_KEY:
        print("Error: HYDRADB_API_KEY is not set.")
        return False
        
    url = f"{BASE_URL}/memories/add_memory"
    payload = {
        "tenant_id": tenant_id,
        "sub_tenant_id": "main",
        "memories": [
            {"text": transcript, "infer": True},
            {"text": f"Video title: {title}", "infer": False}
        ]
    }
    
    try:
        response = requests.post(url, json=payload, headers=get_headers(), timeout=15)
        if response.ok:
            print(f"Successfully stored memories in HydraDB for tenant {tenant_id}.")
            return True
        else:
            print(f"HydraDB add_memory failed with status {response.status_code}: {response.text}")
            return False
    except Exception as e:
        print(f"HydraDB store_memory exception: {e}")
        return False

def recall_context(tenant_id: str, query: str) -> str:
    """
    POST /recall/full_recall with {"tenant_id": tenant_id, "query": query, "sub_tenant_id": "main"}
    Parse response: try data["context"], then data["result"], then join data.get("memories", []) texts
    Return the best context string found, or empty string on failure
    """
    if not Config.HYDRADB_API_KEY:
        print("Error: HYDRADB_API_KEY is not set.")
        return ""
        
    url = f"{BASE_URL}/recall/full_recall"
    payload = {
        "tenant_id": tenant_id,
        "query": query,
        "sub_tenant_id": "main"
    }
    
    try:
        response = requests.post(url, json=payload, headers=get_headers(), timeout=15)
        if response.ok:
            data = response.json()
            
            # Helper to try to retrieve direct or nested properties
            def check_field(field_name, json_data):
                val = json_data.get(field_name)
                if val and isinstance(val, str):
                    return val
                if "data" in json_data and isinstance(json_data["data"], dict):
                    val = json_data["data"].get(field_name)
                    if val and isinstance(val, str):
                        return val
                return None
                
            # 1. Try "context"
            context = check_field("context", data)
            if context:
                return context
                
            # 2. Try "result"
            result = check_field("result", data)
            if result:
                return result
                
            # 3. Try "memories"
            memories = data.get("memories")
            if not memories and "data" in data and isinstance(data["data"], dict):
                memories = data["data"].get("memories")
                
            if memories and isinstance(memories, list):
                memory_texts = []
                for item in memories:
                    if isinstance(item, dict) and "text" in item:
                        memory_texts.append(item["text"])
                    elif isinstance(item, str):
                        memory_texts.append(item)
                if memory_texts:
                    return "\n".join(memory_texts)
                    
            print(f"HydraDB full_recall response was successful but empty or in an unrecognized structure: {data}")
            return ""
        else:
            print(f"HydraDB full_recall failed with status {response.status_code}: {response.text}")
            return ""
    except Exception as e:
        print(f"HydraDB recall_context exception: {e}")
        return ""

def delete_tenant(tenant_id: str) -> bool:
    """
    Deletes the tenant from HydraDB.
    Although not strictly detailed, the DELETE route specifies:
    "deletes session from DB + HydraDB if possible"
    We can POST /tenants/delete or similar, let's see if there is an endpoint.
    Typically: DELETE /tenants/delete or POST /tenants/delete
    Let's try: POST /tenants/delete with {"tenant_id": tenant_id}
    """
    if not Config.HYDRADB_API_KEY:
        return False
        
    url = f"{BASE_URL}/tenants/delete"
    try:
        response = requests.post(url, json={"tenant_id": tenant_id}, headers=get_headers(), timeout=10)
        if response.ok:
            print(f"Successfully deleted tenant {tenant_id} from HydraDB.")
            return True
        else:
            # Let's also try DELETE /tenants/delete?tenant_id={tenant_id} just in case
            url_alt = f"{BASE_URL}/tenants/delete?tenant_id={tenant_id}"
            response_alt = requests.delete(url_alt, headers=get_headers(), timeout=10)
            if response_alt.ok:
                print(f"Successfully deleted tenant {tenant_id} from HydraDB (alternative method).")
                return True
            print(f"HydraDB delete_tenant failed: {response.text}")
            return False
    except Exception as e:
        print(f"HydraDB delete_tenant exception: {e}")
        return False
