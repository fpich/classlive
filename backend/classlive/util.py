"""Utilitaires pour ClassLive."""
from __future__ import annotations

import socket
from typing import Optional


def get_lan_ip(port: int = 8080, protocol: str = 'http') -> Optional[str]:
    """Découvre automatiquement l'adresse IP LAN de la machine.
    
    Retourne une URL complète comme 'http://192.168.1.100:8080' ou None si aucune IP LAN trouvée.
    Test les interfaces réseau et brûle les faux-positifs (localhost, IPv6, etc.).
    """
    try:
        hostname = socket.gethostname()
        ip_list = socket.gethostbyname_ex(hostname)[2]
        
        for ip in ip_list:
            # Ignorer localhost et les adresses non-IPv4
            if not ip.startswith('127.') and '.' in ip and ':' not in ip:
                # Vérifier que c'est une adresse privée (RFC 1918)
                octets = ip.split('.')
                if len(octets) == 4:
                    first_octet = int(octets[0])
                    # 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
                    if (first_octet == 10 or 
                        (first_octet == 172 and 16 <= int(octets[1]) <= 31) or
                        (first_octet == 192 and int(octets[1]) == 168)):
                        return f"{protocol}://{ip}:{port}"
    except Exception:
        pass
    
    # Essayer une autre approche : lister toutes les interfaces
    try:
        for iface in socket.if_nameindex():
            try:
                addrinfo = socket.getaddrinfo(iface[1], None)
                for info in addrinfo:
                    addr = info[4][0]
                    if not addr.startswith('127.') and '.' in addr and ':' not in addr:
                        octets = addr.split('.')
                        if len(octets) == 4:
                            first_octet = int(octets[0])
                            if (first_octet == 10 or 
                                (first_octet == 172 and 16 <= int(octets[1]) <= 31) or
                                (first_octet == 192 and int(octets[1]) == 168)):
                                return f"{protocol}://{addr}:{port}"
            except Exception:
                continue
    except Exception:
        pass
    
    return None


def get_public_url_from_configOr_autodetect(port: int = 8080, protocol: str = 'http', workdir: str | None = None) -> str:
    """Récupère l'URL publique depuis expose.conf ou la détecte automatiquement.
    
    Args:
        port: Port du serveur
        protocol: Protocole (http ou https)
        workdir: Répertoire de travail pour chercher expose.conf
        
    Returns:
        URL publique ou détectée
    """
    import os
    from pathlib import Path
    
    # Essayer de lire depuis expose.conf
    if workdir:
        conf_path = Path(workdir) / 'expose.conf'
        if conf_path.is_file():
            content = conf_path.read_text(encoding='utf-8').strip()
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith('#'):
                    if line.startswith(('http://', 'https://')):
                        return line.rstrip('/')
    
    # Essayer le fichier expose.conf à côté du dépôt
    conf_path = Path(__file__).resolve().parents[2] / 'expose.conf'
    if conf_path.is_file():
        content = conf_path.read_text(encoding='utf-8').strip()
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith('#'):
                if line.startswith(('http://', 'https://')):
                    return line.rstrip('/')
    
    # Détection automatique
    auto_url = get_lan_ip(port, protocol)
    if auto_url:
        return auto_url
    
    # Fallback
    return f"{protocol}://localhost:{port}"
