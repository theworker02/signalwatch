import uvicorn
if __name__=='__main__':
    # For safety, development mode binds only to loopback.
    uvicorn.run('signalwatch.app:app',host='127.0.0.1',port=8765,workers=1)
