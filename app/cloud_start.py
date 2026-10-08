"""Cloud entry point: single worker, persistent data, password required."""
import os


def main():
    os.environ['JOBFLOW_ONLINE'] = '1'
    if not os.getenv('JOBFLOW_DATA_DIR'):
        raise RuntimeError('Configura JOBFLOW_DATA_DIR en un disco persistente antes de iniciar.')
    from .web_auth import validate_online_config
    validate_online_config()
    import uvicorn
    uvicorn.run('app.main:app', host='0.0.0.0', port=int(os.getenv('PORT', '8000')),
                workers=1, proxy_headers=True)


if __name__ == '__main__':
    main()
