# test_keycloak.py
"""
Script de teste para validar a integração com KeyCloak
"""

import requests
import sys
import os

# Adiciona o diretório atual ao path para importar os módulos
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from keycloak_auth import KeyCloakAuthenticator

def test_keycloak_token():
    """Testa a obtenção de token do KeyCloak"""
    print("🔐 Testando autenticação KeyCloak...")
    
    # Configurações do KeyCloak (mesmo do YAML)
    auth_url = "https://lus.rr.sebrae.com.br/realms/sebrae-corporate/protocol/openid-connect/token"
    client_id = "hubcount"
    client_secret = "7nI3Ttz2v4TFdN4d5xujB8pPYUMXVTSw"
    
    try:
        # Cria o autenticador
        auth = KeyCloakAuthenticator(auth_url, client_id, client_secret)
        
        # Tenta obter token
        token = auth.get_access_token()
        
        print(f"✅ Token obtido com sucesso!")
        print(f"   Tamanho do token: {len(token)} caracteres")
        print(f"   Primeiros 50 caracteres: {token[:50]}...")
        
        # Testa headers de autorização
        headers = auth.get_auth_headers()
        print(f"✅ Headers de autorização criados:")
        print(f"   Authorization: Bearer {headers['Authorization'][:20]}...")
        print(f"   Content-Type: {headers['Content-Type']}")
        
        return True
        
    except Exception as e:
        print(f"❌ Erro ao obter token: {e}")
        return False

def test_api_call():
    """Testa uma chamada de API usando o token"""
    print("\n🌐 Testando chamada para API local...")
    
    try:
        # Testa endpoint local
        response = requests.get("http://127.0.0.1:5000/api/keycloak/test")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Teste local bem-sucedido:")
            print(f"   Status: {data.get('ok')}")
            print(f"   Mensagem: {data.get('message')}")
            print(f"   Token obtido: {data.get('has_token')}")
        else:
            print(f"❌ Erro no teste local: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"❌ Erro na chamada de teste: {e}")

if __name__ == "__main__":
    print("🚀 Iniciando testes de integração KeyCloak + RM APIs\n")
    
    # Teste 1: Autenticação KeyCloak
    token_ok = test_keycloak_token()
    
    # Teste 2: API local (se app estiver rodando)
    test_api_call()
    
    print(f"\n📊 Resultado dos testes:")
    print(f"   KeyCloak: {'✅ OK' if token_ok else '❌ FALHOU'}")
    print(f"\n🔧 Para testar com APIs reais do RM:")
    print(f"   1. Ajuste as URLs das APIs no hubcount_config.yml")
    print(f"   2. Configure os endpoints corretos nas métricas")
    print(f"   3. Execute: python app.py")
    print(f"   4. Acesse: http://127.0.0.1:5000")