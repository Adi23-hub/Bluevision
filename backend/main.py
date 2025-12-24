# In backend/main.py

# --- ADD THESE IMPORTS ---
from pydantic import BaseModel
from sqlalchemy.orm import Session
from fastapi import Depends
from .database import SessionLocal, create_db_and_tables, User
from .security import get_password_hash
# --- END NEW IMPORTS ---
import time
import shutil
from pathlib import Path
from fastapi import (
    FastAPI, Request, UploadFile, File, Form, 
    HTTPException
)
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# --- FIX: Changed imports to use the 'backend' package prefix ---
# Since this file (main.py) is inside the 'backend' package, 
# and the app is run using 'uvicorn backend.main:app', we must reference 
# other modules within the package (like feature_extraction and geometry_engine)
# using the 'backend.' prefix.
from backend.feature_extraction import extract_polygons_from_image, find_features
from backend.geometry_engine import build_3d_model


# Initialize FastAPI
app = FastAPI(title="Blueprint 2 3D")
# --- ADD THIS STARTUP EVENT ---
@app.on_event("startup")
def on_startup():
    # This will create the 'miniproject.db' file and User table
    # when the server first starts.
    print("Creating database and tables...")
    create_db_and_tables()
    print("Database and tables created.")
# --- END STARTUP EVENT ---
# --- Pydantic model for receiving user data ---
class UserCreate(BaseModel):
    email: str
    password: str

# --- Dependency to get a database session ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
# --- END DB DEPENDENCY ---

# --- Directory paths ---
BACKEND_DIR = Path(__file__).resolve().parent
BASE_DIR = BACKEND_DIR.parent # This is the correct 'MINI PROJECT' folder
FRONTEND_DIR = BASE_DIR / "frontend" 
UPLOAD_DIR = BACKEND_DIR / "uploads"
MODELS_DIR = BACKEND_DIR / "models"

UPLOAD_DIR.mkdir(exist_ok=True)
MODELS_DIR.mkdir(exist_ok=True)

# Mount static files and templates
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
app.mount("/models", StaticFiles(directory=MODELS_DIR), name="models")
templates = Jinja2Templates(directory=FRONTEND_DIR)

# --- Routes ---
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serves the main 2dto3d.html page."""
    return templates.TemplateResponse("2dto3d.html", {"request": request})

@app.post("/convert")
async def convert_blueprint_to_3d(
    request: Request,
    blueprint_file: UploadFile = File(...),
    wall_height: float = Form(3.0),
    wall_thickness: int = Form(5)
):
    """
    Handles the 2D to 3D conversion process.
    Receives an image, finds walls, doors, and windows,
    builds a 3D model, and returns a JSON response.
    """
    upload_path = UPLOAD_DIR / blueprint_file.filename
    try:
        with open(upload_path, "wb") as buffer:
            shutil.copyfileobj(blueprint_file.file, buffer)
        print(f"Saved file: {upload_path}")
    except Exception as e:
        print(f"Could not save file: {e}")
        return JSONResponse(status_code=500, content={
            "success": False,
            "error_message": f"Could not save file: {e}"
        })

    # --- START CACHE BUSTER FIX ---
    # Create a unique ID from the current time
    cache_buster = int(time.time())
    # Add the unique ID to the filename
    model_filename = f"{Path(blueprint_file.filename).stem}_{cache_buster}.obj"
    # --- END CACHE BUSTER FIX ---

    output_model_path = MODELS_DIR / model_filename
    model_url = f"/models/{model_filename}"

    try:
        # --- 1. Find Walls ---
        # NOTE: The implementation of extract_polygons_from_image should ensure 
        # it returns an empty list or raises a specific error if processing fails.
        wall_polygons = extract_polygons_from_image(str(upload_path))
        if not wall_polygons:
            print("[ERROR] No wall features detected.")
            return JSONResponse(status_code=400, content={
                "success": False,
                "error_message": "No wall features detected. Check image contrast/threshold."
            })
        print(f"[INFO] Found {len(wall_polygons)} wall polygons.")

        # --- 2. Find Doors (PATH FIXED) ---
        # We look in BASE_DIR (the project root) now
        door_template_path = str(BACKEND_DIR / "door_template.png") 
        door_polygons = find_features(str(upload_path), door_template_path, threshold=0.7)
        print(f"[INFO] Found {len(door_polygons)} doors.")

        # --- 3. Find Windows (PATH FIXED) ---
        # We look in BASE_DIR (the project root) now
        window_template_path = str(BACKEND_DIR / "window_template.png")
        window_polygons = find_features(str(upload_path), window_template_path, threshold=0.7)
        print(f"[INFO] Found {len(window_polygons)} windows.")
        
       # (Inside the /convert function in main.py)
        final_model = build_3d_model(
            wall_polygons=wall_polygons, # Correct
            door_polygons=door_polygons, # Correct
            window_polygons=window_polygons, # Correct
            wall_height=wall_height, # Correct
            wall_thickness_pixels=wall_thickness # Correct
        )

        # --- 5. Export and Respond ---
        final_model.export(output_model_path)
        print(f"Conversion successful. Model saved to '{output_model_path}'")
        
        return JSONResponse(content={
            "success": True,
            "model_url": model_url
        })

    except Exception as e:
        # --- FIX: Handle specific model creation error more gracefully ---
        error_message = str(e)
        print(f"An error occurred during conversion: {error_message}")
        
        if "No valid wall meshes could be created" in error_message:
            # This is likely a user input/image quality issue, return 400 Bad Request
            return JSONResponse(status_code=400, content={
                "success": False,
                "error_message": "The uploaded blueprint could not be processed into a 3D model. Please ensure the lines are clear and walls are detectable."
            })
        else:
            # Otherwise, return a generic 500 for a true server side issue
            return JSONResponse(status_code=500, content={
                "success": False,
                "error_message": f"A critical server error occurred: {error_message}"
            })
# In backend/main.py

# ... (your @app.get("/") and @app.post("/convert") routes are here) ...


# --- ADD THIS NEW REGISTRATION ROUTE ---
@app.post("/register")
async def register_user(
    user: UserCreate, 
    db: Session = Depends(get_db)
):
    """
    Handles user registration.
    """
    print(f"Attempting to register user: {user.email}")
    
    # 1. Check if user already exists
    db_user = db.query(User).filter(User.email == user.email).first()
    if db_user:
        print("Error: User with this email already exists.")
        raise HTTPException(
            status_code=400, 
            detail="Email already registered"
        )
        
    # 2. Hash the password
    hashed_password = get_password_hash(user.password)
    
    # 3. Create new user object
    new_db_user = User(
        email=user.email, 
        hashed_password=hashed_password
    )
    
    # 4. Add to database and commit
    try:
        db.add(new_db_user)
        db.commit()
        db.refresh(new_db_user) # Get the new ID back
        print(f"Successfully registered user with ID: {new_db_user.id}")
        return JSONResponse(content={
            "success": True,
            "message": "User created successfully!",
            "user_id": new_db_user.id,
            "email": new_db_user.email
        })
    except Exception as e:
        db.rollback()
        print(f"Error creating user: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Error creating user: {e}"
        )
# --- END NEW ROUTE ---