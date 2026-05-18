from fastapi import FastAPI
from pydantic import BaseModel,Field
from starlette.responses import HTMLResponse

app = FastAPI()


@app.get("/")
async def root():
    return {"message": "Hello World"}

class User(BaseModel):
    username: str=Field(default="张三",ge=2)
    password: str

@app.post("/resigter")
async def resigter(user:User):
    return user

class BookInfo(BaseModel):
    title: str=Field(...,ge=2,le=20)
    author: str=Field(ge=2,le=20)
    publication:str=Field(default="黑马出版社")
    piece:str= Field(...,ge=0)

@app.post("/book")
async def book(info:BookInfo):
    return info

@app.get("/html",response_class=HTMLResponse)
async def get_html():
    return "<h1>这是标题</h1>"