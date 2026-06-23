# cli.py
from connection import SessionLocal
from models.users import User, Profile
import typer
import bcrypt
 

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
 

def createsuperadmin(
    username: str = typer.Option(..., prompt=True, help="Username for the super admin"),
    email: str = typer.Option(..., prompt=True, help="Email address for the user"),
    password: str = typer.Option(..., prompt=True, hide_input=True, help="Password for the user")
):
    """
    Create a super admin user along with a corresponding profile.
    """
    db = SessionLocal()
 
    try:
        # Create a new superadmin user.
        new_user = User(
            username=username,
            email=email,
            password=hash_password(password),
            user_type="superadmin",
            archive=False,
            created_by="CLI",
            last_updated_by="CLI"
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
 
        new_profile = Profile(
            user_id=new_user.id,
            acc_status="Active",
            created_by="CLI",
            last_updated_by="CLI"
        )
        db.add(new_profile)
        db.commit()
        db.refresh(new_profile)
 
        typer.echo(f"Super admin '{username}' with email '{email}' created successfully.")
 
    except Exception as e:
        db.rollback()
        typer.echo(f"Error creating super admin: {e}")
    finally:
        db.close()
 

cli_app = typer.Typer()
cli_app.command()(createsuperadmin)

@cli_app.command()
def runserver():
    """
    Run the FastAPI server.
    """
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
        cli_app()
