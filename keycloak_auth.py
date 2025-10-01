# keycloak_auth.py
"""
Módulo de autenticação KeyCloak para obter tokens de acesso
"""

import time
import requests
from typing import Optional, Dict, Any
from threading import Lock
import logging

logger = logging.getLogger(__name__)

class KeyCloakAuthenticator:
    """Gerenciador de autenticação KeyCloak com cache de token"""
    
    def __init__(self, auth_url: str, client_id: str, client_secret: str):
        """
        Inicializa o autenticador KeyCloak
        
        Args:
            auth_url: URL do endpoint de token do KeyCloak
            client_id: ID do cliente
            client_secret: Secret do cliente
        """
        self.auth_url = auth_url
        self.client_id = client_id
        self.client_secret = client_secret
        
        # Cache do token
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[float] = None
        self._lock = Lock()
        
        # Margem de segurança para renovação (5 minutos antes do vencimento)
        self._renewal_margin = 300
    
    def get_access_token(self) -> str:
        """
        Obtém um token de acesso válido
        
        Returns:
            Token de acesso válido
            
        Raises:
            Exception: Se não conseguir obter o token
        """
        with self._lock:
            # Verifica se o token ainda é válido
            if self._is_token_valid():
                return self._access_token
            
            # Obtém novo token
            return self._fetch_new_token()
    
    def _is_token_valid(self) -> bool:
        """Verifica se o token atual ainda é válido"""
        if not self._access_token or not self._token_expiry:
            return False
        
        # Verifica se o token não expira nos próximos 5 minutos
        return time.time() < (self._token_expiry - self._renewal_margin)
    
    def _fetch_new_token(self) -> str:
        """
        Busca um novo token do KeyCloak
        
        Returns:
            Novo token de acesso
            
        Raises:
            Exception: Se não conseguir obter o token
        """
        try:
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            data = {
                'grant_type': 'client_credentials',
                'client_id': self.client_id,
                'client_secret': self.client_secret
            }
            
            logger.info(f"Obtendo novo token do KeyCloak: {self.auth_url}")
            
            # Configura verificação SSL (pode ser desabilitada para desenvolvimento)
            verify_ssl = True
            if "localhost" in self.auth_url or "127.0.0.1" in self.auth_url:
                verify_ssl = False
            
            response = requests.post(
                self.auth_url,
                headers=headers,
                data=data,
                timeout=30,
                verify=verify_ssl
            )
            
            if response.status_code == 200:
                token_data = response.json()
                
                self._access_token = token_data['access_token']
                expires_in = token_data.get('expires_in', 1800)  # Default 30 minutos
                self._token_expiry = time.time() + expires_in
                
                logger.info(f"Token obtido com sucesso. Expira em {expires_in} segundos")
                return self._access_token
            else:
                error_msg = f"Erro ao obter token: {response.status_code} - {response.text}"
                logger.error(error_msg)
                raise Exception(error_msg)
                
        except requests.exceptions.SSLError as e:
            # Erro específico de SSL
            error_msg = f"Erro de SSL ao conectar com KeyCloak: {str(e)}"
            logger.error(error_msg)
            logger.warning("Tentativa com verificação SSL desabilitada (apenas desenvolvimento)")
            
            try:
                # Segunda tentativa sem verificação SSL (apenas para desenvolvimento)
                response = requests.post(
                    self.auth_url,
                    headers=headers,
                    data=data,
                    timeout=30,
                    verify=False
                )
                
                if response.status_code == 200:
                    token_data = response.json()
                    self._access_token = token_data['access_token']
                    expires_in = token_data.get('expires_in', 1800)
                    self._token_expiry = time.time() + expires_in
                    logger.warning("Token obtido sem verificação SSL")
                    return self._access_token
                else:
                    raise Exception(f"Erro ao obter token (sem SSL): {response.status_code} - {response.text}")
                    
            except Exception as e2:
                raise Exception(f"Erro de SSL e falha na tentativa sem verificação: {str(e2)}")
                
        except requests.exceptions.RequestException as e:
            error_msg = f"Erro de conexão ao obter token: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)
        except Exception as e:
            error_msg = f"Erro inesperado ao obter token: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)
    
    def invalidate_token(self):
        """Invalida o token atual, forçando renovação na próxima chamada"""
        with self._lock:
            self._access_token = None
            self._token_expiry = None
            logger.info("Token invalidado")
    
    def get_auth_headers(self) -> Dict[str, str]:
        """
        Obtém headers de autorização para requisições
        
        Returns:
            Dicionário com headers de autorização
        """
        token = self.get_access_token()
        return {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }


# Instância global do autenticador (será configurada no app.py)
keycloak_auth: Optional[KeyCloakAuthenticator] = None


def initialize_keycloak_auth(auth_url: str, client_id: str, client_secret: str):
    """
    Inicializa o autenticador KeyCloak global
    
    Args:
        auth_url: URL do endpoint de token do KeyCloak
        client_id: ID do cliente
        client_secret: Secret do cliente
    """
    global keycloak_auth
    keycloak_auth = KeyCloakAuthenticator(auth_url, client_id, client_secret)
    logger.info("Autenticador KeyCloak inicializado")


def get_keycloak_auth() -> KeyCloakAuthenticator:
    """
    Obtém a instância do autenticador KeyCloak
    
    Returns:
        Instância do autenticador
        
    Raises:
        Exception: Se o autenticador não foi inicializado
    """
    if keycloak_auth is None:
        raise Exception("Autenticador KeyCloak não foi inicializado")
    return keycloak_auth