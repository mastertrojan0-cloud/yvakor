<!-- skill: criar-api-rest-fastapi | tags: fastapi, api, sqlite, postgresql, python | status: nova -->
# Criar API REST com FastAPI e SQLite/PostgreSQL

## Quando usar
Sempre que precisar expor dados ou funcionalidades via API REST para integração com front-end (React, Vue), chatbots, automações ou sistemas externos. Ideal para micro-SaaS, dashboards e CRUDs.

## Pré-requisitos
- Python 3.9+ instalado
- pip (gerenciador de pacotes)
- Conhecimento básico de Python e HTTP

## Procedimento

1. **Criar ambiente virtual e instalar dependências**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   # ou
   venv\Scripts\activate  # Windows
   pip install fastapi uvicorn sqlalchemy databases
   # Se for PostgreSQL:
   pip install psycopg2-binary
   # Se for SQLite (já incluso no Python, mas databases precisa):
   pip install aiosqlite
   ```

2. **Estruturar o projeto**
   ```
   meu_projeto/
   ├── main.py          # Ponto de entrada da API
   ├── database.py      # Configuração do banco
   ├── models.py        # Modelos SQLAlchemy
   ├── schemas.py       # Schemas Pydantic
   └── crud.py          # Operações CRUD
   ```

3. **Configurar banco de dados (database.py)**
   ```python
   from sqlalchemy import create_engine
   from sqlalchemy.ext.declarative import declarative_base
   from sqlalchemy.orm import sessionmaker

   # Para SQLite:
   SQLALCHEMY_DATABASE_URL = "sqlite:///./{nome_banco}.db"
   engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})

   # Para PostgreSQL (substituir {user}, {password}, {host}, {port}, {dbname}):
   # SQLALCHEMY_DATABASE_URL = "postgresql://{user}:{password}@{host}:{port}/{dbname}"
   # engine = create_engine(SQLALCHEMY_DATABASE_URL)

   SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
   Base = declarative_base()
   ```

4. **Definir modelos (models.py)**
   ```python
   from sqlalchemy import Column, Integer, String, Float, DateTime
   from database import Base
   import datetime

   class {NomeModelo}(Base):
       __tablename__ = "{nome_tabela}"
       
       id = Column(Integer, primary_key=True, index=True)
       {campo1} = Column(String, index=True)
       {campo2} = Column(Float)
       created_at = Column(DateTime, default=datetime.datetime.utcnow)
   ```

5. **Criar schemas Pydantic (schemas.py)**
   ```python
   from pydantic import BaseModel
   from datetime import datetime
   from typing import Optional

   class {NomeModelo}Base(BaseModel):
       {campo1}: str
       {campo2}: float

   class {NomeModelo}Create({NomeModelo}Base):
       pass

   class {NomeModelo}({NomeModelo}Base):
       id: int
       created_at: datetime
       
       class Config:
           orm_mode = True
   ```

6. **Implementar CRUD (crud.py)**
   ```python
   from sqlalchemy.orm import Session
   import models, schemas

   def get_{nome_modelo_lower}(db: Session, {nome_modelo_lower}_id: int):
       return db.query(models.{NomeModelo}).filter(models.{NomeModelo}.id == {nome_modelo_lower}_id).first()

   def get_{nome_modelo_lower}s(db: Session, skip: int = 0, limit: int = 100):
       return db.query(models.{NomeModelo}).offset(skip).limit(limit).all()

   def create_{nome_modelo_lower}(db: Session, {nome_modelo_lower}: schemas.{NomeModelo}Create):
       db_{nome_modelo_lower} = models.{NomeModelo}(**{nome_modelo_lower}.dict())
       db.add(db_{nome_modelo_lower})
       db.commit()
       db.refresh(db_{nome_modelo_lower})
       return db_{nome_modelo_lower}

   def update_{nome_modelo_lower}(db: Session, {nome_modelo_lower}_id: int, {nome_modelo_lower}: schemas.{NomeModelo}Create):
       db_{nome_modelo_lower} = get_{nome_modelo_lower}(db, {nome_modelo_lower}_id)
       if db_{nome_modelo_lower}:
           for key, value in {nome_modelo_lower}.dict().items():
               setattr(db_{nome_modelo_lower}, key, value)
           db.commit()
           db.refresh(db_{nome_modelo_lower})
       return db_{nome_modelo_lower}

   def delete_{nome_modelo_lower}(db: Session, {nome_modelo_lower}_id: int):
       db_{nome_modelo_lower} = get_{nome_modelo_lower}(db, {nome_modelo_lower}_id)
       if db_{nome_modelo_lower}:
           db.delete(db_{nome_modelo_lower})
           db.commit()
       return db_{nome_modelo_lower}
   ```

7. **Criar endpoints (main.py)**
   ```python
   from fastapi import FastAPI, Depends, HTTPException
   from sqlalchemy.orm import Session
   import models, schemas, crud
   from database import SessionLocal, engine

   models.Base.metadata.create_all(bind=engine)

   app = FastAPI(title="{Nome da API}", version="1.0.0")

   # Dependência para sessão
   def get_db():
       db = SessionLocal()
       try:
           yield db
       finally:
           db.close()

   @app.post("/{nome_recurso}/", response_model=schemas.{NomeModelo})
   def create_item(item: schemas.{NomeModelo}Create, db: Session = Depends(get_db)):
       return crud.create_{nome_modelo_lower}(db=db, {nome_modelo_lower}=item)

   @app.get("/{nome_recurso}/", response_model=list[schemas.{NomeModelo}])
   def read_items(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
       items = crud.get_{nome_modelo_lower}s(db, skip=skip, limit=limit)
       return items

   @app.get("/{nome_recurso}/{item_id}", response_model=schemas.{NomeModelo})
   def read_item(item_id: int, db: Session = Depends(get_db)):
       db_item = crud.get_{nome_modelo_lower}(db, item_id)
       if db_item is None:
           raise HTTPException(status_code=404, detail="{NomeModelo} not found")
       return db_item

   @app.put("/{nome_recurso}/{item_id}", response_model=schemas.{NomeModelo})
   def update_item(item_id: int, item: schemas.{NomeModelo}Create, db: Session = Depends(get_db)):
       db_item = crud.update_{nome_modelo_lower}(db, item_id, item)
       if db_item is None:
           raise HTTPException(status_code=404, detail="{NomeModelo} not found")
       return db_item

   @app.delete("/{nome_recurso}/{item_id}")
   def delete_item(item_id: int, db: Session = Depends(get_db)):
       db_item = crud.delete_{nome_modelo_lower}(db, item_id)
       if db_item is None:
           raise HTTPException(status_code=404, detail="{NomeModelo} not found")
       return {"message": "{NomeModelo} deleted successfully"}
   ```

8. **Executar a API**
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```
   Acessar documentação automática em: http://localhost:8000/docs

## Erros conhecidos e soluções

| Erro | Causa | Solução |
|------|-------|---------|
| `ModuleNotFoundError: No module named 'pydantic'` | Dependências não instaladas | Execute `pip install -r requirements.txt` ou instale manualmente |
| `sqlalchemy.exc.OperationalError: unable to open database file` | Caminho do SQLite inválido | Verifique permissões de escrita no diretório |
| `psycopg2.OperationalError: could not connect to server` | PostgreSQL não está rodando | Inicie o serviço: `sudo systemctl start postgresql` |
| `ValueError: Field 'id' not found` | Schema Pydantic sem campo id | Adicione `id: int` no schema de resposta |
| CORS bloqueando requisições do front-end | Falta configuração CORS | Adicione `from fastapi.middleware.cors import CORSMiddleware` e configure origens permitidas |

## Exemplo aplicado ao contexto do usuário

**Cenário**: Criar API para gerenciar clientes da ACM Digital

1. Substituir placeholders:
   - `{NomeModelo}` → `Cliente`
   - `{nome_tabela}` → `clientes`
   - `{campo1}` → `nome`
   - `{campo2}` → `telefone` (String)
   - `{nome_recurso}` → `clientes`
   - `{Nome da API}` → `ACM Digital - Clientes API`

2. Executar:
   ```bash
   uvicorn main:app --reload --port 8000
   ```

3. Testar com curl:
   ```bash
   # Criar cliente
   curl -X POST http://localhost:8000/clientes/ -H "Content-Type: application/json" -d '{"nome": "João Silva", "telefone": "92999999999"}'
   
   # Listar clientes
   curl http://localhost:8000/clientes/
   ```

**Integração com front-end React**: Adicionar CORS em main.py:
```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # URL do React
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```
