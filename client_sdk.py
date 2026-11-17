# client_sdk.py
import requests
import platform
import json
import uuid
import os
import socket
import hashlib
import logging
import datetime
from typing import Dict, Any, Optional, Tuple

class LicenseClient:
    """
    Client SDK for integrating with the license server.
    
    Usage:
        license_client = LicenseClient(
            license_key="XXXX-XXXX-XXXX-XXXX",
            api_key="your_api_key",
            api_url="http://license.server.com/api/v1"
        )
        
        # Validate and activate a license
        if license_client.activate():
            print("License activated successfully!")
        else:
            print(f"License activation failed: {license_client.last_error}")
            
        # Periodically check license status
        if license_client.check_license():
            # License is still valid
            pass
        else:
            # License is no longer valid
            print(f"License check failed: {license_client.last_error}")
            
        # When application closes
        license_client.deactivate()
    """
    
    def __init__(self, license_key: str, api_key: str, api_url: str, 
                 app_name: str = "", app_version: str = "",
                 auto_heartbeat: bool = True, heartbeat_interval: int = 3600):
        """
        Initialize the license client.
        
        Args:
            license_key: The license key to validate
            api_key: The API key for authenticating with the license server
            api_url: The base URL of the license server API
            app_name: Name of the application (for reporting)
            app_version: Version of the application (for reporting)
            auto_heartbeat: Whether to automatically send heartbeats in the background
            heartbeat_interval: How often to send heartbeats (in seconds)
        """
        self.license_key = license_key
        self.api_key = api_key
        self.api_url = api_url.rstrip('/')
        self.app_name = app_name
        self.app_version = app_version
        
        self.activation_id = None
        self.last_error = None
        self.is_activated = False
        self.license_info = None
        
        self.auto_heartbeat = auto_heartbeat
        self.heartbeat_interval = heartbeat_interval
        self.heartbeat_timer = None
        
        # Set up logging
        self.logger = logging.getLogger("license_client")
        
        # For persistence
        self.data_dir = os.path.join(os.path.expanduser("~"), ".license_client")
        os.makedirs(self.data_dir, exist_ok=True)
        
    def _get_system_info(self) -> Dict[str, Any]:
        """
        Collect system information for hardware fingerprinting.
        """
        system_info = {
            "platform": platform.system(),
            "platform_release": platform.release(),
            "platform_version": platform.version(),
            "architecture": platform.machine(),
            "hostname": socket.gethostname(),
            "cpu": {
                "processor": platform.processor(),
                "model": "Unknown"
            },
            "network": {
                "mac_addresses": self._get_mac_addresses()
            }
        }
        
        # Try to get more detailed CPU info on supported platforms
        try:
            if platform.system() == "Linux":
                with open("/proc/cpuinfo", "r") as f:
                    for line in f:
                        if "model name" in line:
                            system_info["cpu"]["model"] = line.split(":")[1].strip()
                            break
            elif platform.system() == "Darwin":  # macOS
                import subprocess
                output = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"]).decode().strip()
                system_info["cpu"]["model"] = output
            elif platform.system() == "Windows":
                import winreg
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, 
                                      r"HARDWARE\\DESCRIPTION\\System\\CentralProcessor\\0")
                system_info["cpu"]["model"] = winreg.QueryValueEx(key, "ProcessorNameString")[0]
        except Exception as e:
            self.logger.warning(f"Failed to get detailed CPU info: {e}")
        
        # Try to get machine ID for more stable fingerprinting
        try:
            if platform.system() == "Linux":
                with open("/etc/machine-id", "r") as f:
                    system_info["machine_id"] = f.read().strip()
            elif platform.system() == "Darwin":  # macOS
                import subprocess
                output = subprocess.check_output(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"]).decode()
                for line in output.split('\n'):
                    if "IOPlatformUUID" in line:
                        system_info["machine_id"] = line.split('"')[3]
                        break
            elif platform.system() == "Windows":
                import winreg
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, 
                                      r"SOFTWARE\\Microsoft\\Cryptography")
                system_info["machine_id"] = winreg.QueryValueEx(key, "MachineGuid")[0]
        except Exception as e:
            self.logger.warning(f"Failed to get machine ID: {e}")
            # Generate a persistent machine ID
            machine_id_path = os.path.join(self.data_dir, "machine_id")
            if os.path.exists(machine_id_path):
                with open(machine_id_path, "r") as f:
                    system_info["machine_id"] = f.read().strip()
            else:
                system_info["machine_id"] = str(uuid.uuid4())
                with open(machine_id_path, "w") as f:
                    f.write(system_info["machine_id"])
        
        return system_info
    
    def _generate_hardware_fingerprint(self, system_info) -> str:
        """
        Generate a consistent hardware fingerprint based on system information.
        
        Returns:
            str: Hardware fingerprint as SHA-256 hash
        """
        fingerprint_data = {
            "platform": system_info.get("platform", ""),
            "platform_release": system_info.get("platform_release", ""),
            "platform_version": system_info.get("platform_version", ""),
            "architecture": system_info.get("architecture", ""),
            "hostname": system_info.get("hostname", ""),
            "machine_id": system_info.get("machine_id", "")
        }
        
        # Create a deterministic string by sorting keys
        fingerprint_str = json.dumps(fingerprint_data, sort_keys=True)
        return hashlib.sha256(fingerprint_str.encode()).hexdigest()
    
    def _get_mac_addresses(self) -> list:
        """
        Get MAC addresses of all network interfaces.
        """
        mac_addresses = []
        
        try:
            if platform.system() == "Windows":
                import subprocess
                output = subprocess.check_output("ipconfig /all").decode()
                for line in output.split('\n'):
                    if "Physical Address" in line:
                        mac = line.split(":")[1].strip()
                        if mac != "00-00-00-00-00-00":
                            mac_addresses.append(mac)
            else:  # Linux and macOS
                import uuid
                import re
                
                for interface in os.listdir('/sys/class/net/') if platform.system() == "Linux" else []:
                    try:
                        with open(f"/sys/class/net/{interface}/address", "r") as f:
                            mac = f.read().strip()
                            if mac != "00:00:00:00:00:00":
                                mac_addresses.append(mac)
                    except:
                        pass
                
                if not mac_addresses and platform.system() == "Darwin":  # macOS fallback
                    import subprocess
                    output = subprocess.check_output(["ifconfig"]).decode()
                    for line in output.split('\n'):
                        if "ether" in line:
                            mac = re.search(r'([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})', line).group(0)
                            mac_addresses.append(mac)
        except Exception as e:
            self.logger.warning(f"Failed to get MAC addresses: {e}")
        
        return mac_addresses
    
    def _make_request(self, endpoint: str, data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Make a request to the license server API using sessions.
        
        Returns:
            Tuple[bool, Dict[str, Any]]: (success, response_data)
        """
        url = f"{self.api_url}/{endpoint}"
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": f"LicenseClient/{self.app_name}/{self.app_version}"
        }
        
        try:
            session = requests.Session()
            request = requests.Request('POST', url, json=data, headers=headers)
            prepared_request = session.prepare_request(request)
            response = session.send(prepared_request)
            
            if response.status_code == 200:
                return True, response.json()
            else:
                error_msg = f"API request failed with status {response.status_code}"
                try:
                    error_data = response.json()
                    if "detail" in error_data:
                        error_msg = error_data["detail"]
                except:
                    pass
                
                self.last_error = error_msg
                return False, {"error": error_msg}
        
        except requests.RequestException as e:
            self.last_error = f"Network error: {str(e)}"
            return False, {"error": self.last_error}
        except Exception as e:
            self.last_error = f"Unexpected error: {str(e)}"
            return False, {"error": self.last_error}
    
    def validate(self) -> bool:
        """
        Validate the license key without activating it.
        
        Returns:
            bool: True if the license is valid, False otherwise
        """
        data = {
            "license_key": self.license_key,
            "app_name": self.app_name,
            "app_version": self.app_version
        }
        
        success, response = self._make_request("validate", data)
        
        if success and response.get("valid", False):
            self.license_info = response
            return True
        
        return False
    
    def activate(self) -> bool:
        """
        Validate and activate the license for this device.
        
        Returns:
            bool: True if activation was successful, False otherwise
        """
        system_info = self._get_system_info()
        # Generate hardware fingerprint
        hardware_id = self._generate_hardware_fingerprint(system_info)
        
        # Get IP address
        ip_address = self._get_ip_address()
        
        data = {
            "license_key": self.license_key,
            "ip_address": ip_address,
            "system_info": system_info,
            "hardware_id": hardware_id,
            "user_agent": f"LicenseClient/{self.app_name}/{self.app_version}"
        }
        
        success, response = self._make_request("activate", data)
        
        if success and response.get("success", False):
            self.is_activated = True
            self.activation_id = response.get("activation_id")
            
            # Store activation data
            self._store_activation_data()
            
            # Start heartbeat if enabled
            if self.auto_heartbeat:
                self._start_heartbeat()
            
            return True
        
        return False
    
    def deactivate(self) -> bool:
        """
        Deactivate the license on this device.
        
        Returns:
            bool: True if deactivation was successful, False otherwise
        """
        if not self.is_activated:
            return True  # Already deactivated
        
        system_info = self._get_system_info()
        
        # Generate hardware fingerprint
        hardware_id = self._generate_hardware_fingerprint(system_info)
        
        data = {
            "license_key": self.license_key,
            "system_info": system_info,
            "hardware_id": hardware_id
        }
        
        success, response = self._make_request("deactivate", data)
        
        if success and response.get("success", False):
            self.is_activated = False
            self.activation_id = None
            
            # Remove activation data
            self._clear_activation_data()
            
            # Stop heartbeat
            self._stop_heartbeat()
            
            return True
        
        return False
    
    def check_license(self) -> bool:
        """
        Check if the license is still valid by sending a heartbeat.
        
        Returns:
            bool: True if the license is still valid, False otherwise
        """
        if not self.is_activated or not self.activation_id:
            self.last_error = "License not activated"
            return False
        
        system_info = self._get_system_info()
        
        data = {
            "activation_id": self.activation_id,
            "system_info": system_info
        }
        
        success, response = self._make_request("heartbeat", data)
        
        if success and response.get("valid", False):
            return True
        
        # If the heartbeat fails, the license might be revoked or expired
        if success:
            self.last_error = response.get("message", "License is no longer valid")
        
        return False
    
    def _get_ip_address(self) -> str:
        """
        Get the current public IP address.
        """
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"
    
    def _store_activation_data(self) -> None:
        """
        Store activation data for persistence across application restarts.
        """
        data = {
            "license_key": self.license_key,
            "activation_id": self.activation_id,
            "timestamp": str(datetime.datetime.now()),
            "app_name": self.app_name,
            "app_version": self.app_version
        }
        
        file_path = os.path.join(self.data_dir, "activation.json")
        
        try:
            with open(file_path, "w") as f:
                json.dump(data, f)
        except Exception as e:
            self.logger.warning(f"Failed to store activation data: {e}")
    
    def _clear_activation_data(self) -> None:
        """
        Clear stored activation data.
        """
        file_path = os.path.join(self.data_dir, "activation.json")
        
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                self.logger.warning(f"Failed to clear activation data: {e}")
    
    def _load_activation_data(self) -> bool:
        """
        Load activation data from stored file.
        
        Returns:
            bool: True if activation data was loaded successfully, False otherwise
        """
        file_path = os.path.join(self.data_dir, "activation.json")
        
        if not os.path.exists(file_path):
            return False
        
        try:
            with open(file_path, "r") as f:
                data = json.load(f)
            
            if data.get("license_key") == self.license_key:
                self.activation_id = data.get("activation_id")
                self.is_activated = True
                return True
        except Exception as e:
            self.logger.warning(f"Failed to load activation data: {e}")
        
        return False
    
    def _start_heartbeat(self) -> None:
        """
        Start the heartbeat timer to periodically check license status.
        """
        if self.heartbeat_timer:
            return  # Already running
        
        import threading
        
        def heartbeat_task():
            self.logger.debug("Sending license heartbeat")
            self.check_license()
            
            # Schedule next heartbeat
            self.heartbeat_timer = threading.Timer(self.heartbeat_interval, heartbeat_task)
            self.heartbeat_timer.daemon = True
            self.heartbeat_timer.start()
        
        # Start first heartbeat
        self.heartbeat_timer = threading.Timer(self.heartbeat_interval, heartbeat_task)
        self.heartbeat_timer.daemon = True
        self.heartbeat_timer.start()
    
    def _stop_heartbeat(self) -> None:
        """
        Stop the heartbeat timer.
        """
        if self.heartbeat_timer:
            self.heartbeat_timer.cancel()
            self.heartbeat_timer = None