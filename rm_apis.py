# rm_apis.py
"""
Módulo para integração com APIs do RM (Royal Management)
"""

import requests
import json
from typing import Any, Dict, List, Optional
from abc import ABC, abstractmethod
import logging
from keycloak_auth import get_keycloak_auth

logger = logging.getLogger(__name__)

class RMAPIBase(ABC):
    """Classe base para APIs do RM"""
    
    def __init__(self, name: str, base_url: str, timeout: int = 30):
        """
        Inicializa a API base
        
        Args:
            name: Nome identificador da API
            base_url: URL base da API
            timeout: Timeout para requisições em segundos
        """
        self.name = name
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """
        Faz uma requisição autenticada para a API
        
        Args:
            method: Método HTTP (GET, POST, etc.)
            endpoint: Endpoint da API (relativo à base_url)
            **kwargs: Parâmetros adicionais para requests
            
        Returns:
            Resposta da API como dicionário
            
        Raises:
            Exception: Se a requisição falhar
        """
        try:
            # Obtém headers de autenticação
            auth = get_keycloak_auth()
            headers = auth.get_auth_headers()
            
            # Combina headers fornecidos com headers de auth
            if 'headers' in kwargs:
                headers.update(kwargs['headers'])
            kwargs['headers'] = headers
            
            # Define timeout se não fornecido
            if 'timeout' not in kwargs:
                kwargs['timeout'] = self.timeout
            
            # Monta URL completa
            url = f"{self.base_url}/{endpoint.lstrip('/')}"
            
            logger.debug(f"Fazendo requisição {method} para {url}")
            
            # Faz a requisição
            response = requests.request(method, url, **kwargs)
            
            if response.status_code == 401:
                # Token expirado, tenta renovar e fazer nova requisição
                logger.warning("Token expirado, renovando...")
                auth.invalidate_token()
                headers = auth.get_auth_headers()
                kwargs['headers'].update(headers)
                response = requests.request(method, url, **kwargs)
            
            if response.status_code >= 400:
                error_msg = f"Erro na API {self.name}: {response.status_code} - {response.text}"
                logger.error(error_msg)
                raise Exception(error_msg)
            
            # Tenta parsear como JSON, senão retorna texto
            try:
                return response.json()
            except json.JSONDecodeError:
                return {"data": response.text, "content_type": response.headers.get('content-type')}
                
        except requests.exceptions.RequestException as e:
            error_msg = f"Erro de conexão na API {self.name}: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)
    
    def get(self, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Faz requisição GET"""
        return self._make_request('GET', endpoint, **kwargs)
    
    def post(self, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Faz requisição POST"""
        return self._make_request('POST', endpoint, **kwargs)
    
    def put(self, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Faz requisição PUT"""
        return self._make_request('PUT', endpoint, **kwargs)
    
    def delete(self, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Faz requisição DELETE"""
        return self._make_request('DELETE', endpoint, **kwargs)
    
    @abstractmethod
    def execute_query(self, query: str) -> List[Dict[str, Any]]:
        """
        Executa uma 'query' na API e retorna dados estruturados
        
        Args:
            query: Query/parâmetros específicos da API
            
        Returns:
            Lista de dicionários com os dados
        """
        pass


class RMAPI(RMAPIBase):
    """Implementação genérica de API do RM"""
    
    def execute_query(self, query: str) -> List[Dict[str, Any]]:
        """
        Executa uma query genérica na API
        
        A query pode ser:
        - Um endpoint simples: "/usuarios"
        - Um endpoint com parâmetros: "/usuarios?status=ativo"
        - JSON para POST: '{"method": "POST", "endpoint": "/search", "data": {...}}'
        
        Args:
            query: Query a ser executada
            
        Returns:
            Lista de dicionários com os dados
        """
        try:
            # Tenta parsear como JSON (para queries complexas)
            try:
                query_data = json.loads(query)
                if isinstance(query_data, dict):
                    method = query_data.get('method', 'GET')
                    endpoint = query_data['endpoint']
                    data = query_data.get('data')
                    params = query_data.get('params')
                    
                    kwargs = {}
                    if data:
                        kwargs['json'] = data
                    if params:
                        kwargs['params'] = params
                    
                    result = self._make_request(method, endpoint, **kwargs)
                else:
                    # Se não é dict, trata como endpoint simples
                    result = self.get(query)
            except json.JSONDecodeError:
                # Query simples, faz GET
                result = self.get(query)
            
            # Normaliza o resultado para lista de dicionários
            if isinstance(result, list):
                return result
            elif isinstance(result, dict):
                # Se o resultado tem uma chave de dados comum
                if 'data' in result and isinstance(result['data'], list):
                    return result['data']
                elif 'items' in result and isinstance(result['items'], list):
                    return result['items']
                elif 'results' in result and isinstance(result['results'], list):
                    return result['results']
                else:
                    # Retorna o dict como item único da lista
                    return [result]
            else:
                # Resultado não estruturado
                return [{"value": result}]
                
        except Exception as e:
            logger.error(f"Erro ao executar query na API {self.name}: {str(e)}")
            raise


class RMAPIFactory:
    """Factory para criar instâncias de APIs do RM"""
    
    @staticmethod
    def create_api(api_config: Dict[str, Any]) -> RMAPIBase:
        """
        Cria uma instância de API baseada na configuração
        
        Args:
            api_config: Configuração da API
            
        Returns:
            Instância da API
        """
        api_type = api_config.get('type', 'rm-api')
        name = api_config['name']
        base_url = api_config['base_url']
        timeout = api_config.get('timeout', 30)
        
        if api_type == 'rm-api':
            return RMAPI(name, base_url, timeout)
        else:
            # Para futuras implementações específicas
            raise ValueError(f"Tipo de API não suportado: {api_type}")


# Cache de instâncias de APIs
_api_cache: Dict[str, RMAPIBase] = {}

def get_rm_api(name: str, config: Dict[str, Any]) -> RMAPIBase:
    """
    Obtém uma instância de API do RM (com cache)
    
    Args:
        name: Nome da API
        config: Configuração da API
        
    Returns:
        Instância da API
    """
    if name not in _api_cache:
        _api_cache[name] = RMAPIFactory.create_api(config)
    return _api_cache[name]

def clear_api_cache():
    """Limpa o cache de APIs"""
    global _api_cache
    _api_cache.clear()