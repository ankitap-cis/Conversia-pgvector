from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from api.roleplay_assistant.features.course_services import admin_coursefile_to_vectordb
from models.roleplay_models import Persona, Evaluation, Scenario, EvaluationField
from models.courses_models import Course
import configparser
from logger import *
from utils.s3_bucket_helper import generate_presigned_url, get_s3_client


config = configparser.ConfigParser()
config.read('config.ini')

db_name = config['database']['db_name']
db_host = config['database']['host']
db_port = config['database']['port']
db_username = config['database']['username']
db_password = config['database']['password']

DATABASE_URL = f"postgresql://{db_username}:{db_password}@{db_host}:{db_port}/{db_name}"


# Set up the database engine and session
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Function to create Persona
def create_persona(session, role, primary_goal, challenges, objections, motivations, fears, communication_style, behavioral_tendencies, thumbnail, avatar_id, created_by, last_updated_by):
    persona = Persona(
        role=role,
        primary_goal=primary_goal,
        challenges=challenges,
        objections=objections,
        motivations=motivations,
        fears=fears,
        communication_style=communication_style,
        behavioral_tendencies=behavioral_tendencies,
        thumbnail=thumbnail,
        avatar_id=avatar_id,
        created_by=created_by,
        last_updated_by=last_updated_by
    )
    session.add(persona)
    return persona


# Function to create Evaluation
def create_evaluation(session, title, description, created_by, fields: list):
    evaluation = Evaluation(
        title=title,
        description=description,
        created_by=created_by,
        last_updated_by=created_by
    )
    session.add(evaluation)
    session.flush()

    criteria_fields = []
    for field in fields:
        # Create the EvaluationField and associate it with the created Evaluation
        new_field = EvaluationField(
            title_area=field["title_area"],
            rating=field["rating"],
            weight=field["weight"],
            comment=field.get("comment"),  # Comment is optional
            evaluation_id=evaluation.id
        )
        session.add(new_field)
        criteria_fields.append(new_field)
    return evaluation


# Function to create Scenario
def create_scenario(session, title, scenario_image, description, persona_id, evaluation_id, created_by, ai_trainer_opening, selling_methodology, ideal_sales_outcome, topics_to_cover, current_state, barriers_to_change, critical_questions):
    scenario = Scenario(
        title=title,
        scenario_image=scenario_image,
        description=description,
        ai_trainer_opening=ai_trainer_opening,
        selling_methodology=selling_methodology,
        ideal_sales_outcome=ideal_sales_outcome,
        topics_to_cover=topics_to_cover,
        current_state=current_state,
        barriers_to_change=barriers_to_change,
        critical_questions=critical_questions,
        persona_id=persona_id,
        evaluation_id=evaluation_id,
        created_by=created_by,
        last_updated_by=created_by
    )
    session.add(scenario)
    return scenario


# Function to create Course
def create_course(session, title, audience, description, image_url, course_file_url, created_by, instructor_id):
    course = Course(
        title=title,
        audience=audience,
        description=description,
        image_url=image_url,
        course_file_url=course_file_url,
        created_by=created_by,
        last_updated_by=created_by,
        instructor_id=instructor_id
    )
    session.add(course)
    return course

async def default_samples(db, current_user):
    try:
        # Createing Personas
        persona1 = create_persona(
            session=db,
            role="Interventional cardiologist and cath lab medical director at a regional hospital.",
            primary_goal="Deliver excellent patient care, save lives and help patients achieve quality of life.",
            challenges="Resource limitations in the hospital. Resistance to change from administration and peers.",
            objections="Needs robust clinical studies in addition to clinical validation in real-world settings.",
            motivations="Avoid malpractice lawsuits. Grow practice. Being a leader in cutting-edge therapy ",
            fears="Poor outcomes. Device complications. Appearing that is overusing expensive technology.",
            communication_style="Formal but practical; Appreciates succinct data-backed conversation.",
            behavioral_tendencies="Skeptical and analytical; Demands strong clinical evidence and peer validation",
            thumbnail="Dr. Michael Alvarez, MD",
            avatar_id="Pedro_Chair_Sitting_public",
            created_by=current_user.email,
            last_updated_by=current_user.email
        )

        persona2 = create_persona(
            session=db,
            role="General Surgeon at an academic medical center.",
            primary_goal="Reduce long-term patient complications (recurrence/pain), maintain high OR throughput, and publish clinical outcomes.",
            challenges="Managing patient complaints regarding chronic pain post-surgery; Administrative pressure to lower supply costs per case.",
            objections="Needs peer validation in real-world settings. Financial: My Value Analysis Committee will kill this if it adds cost without cutting OR time.",
            motivations="Avoid malpractice lawsuits. Outcomes: Desperately wants to avoid the 'pre-discharge mortality' conversation with families. Wants to be seen as an innovator.",
            fears="Trying a new device that causes an intraoperative disaster (safety first). Being an outlier in national databases (STS) for adverse events.",
            communication_style="Direct, data-demanding, impatient with marketing fluff. Wants to speak 'surgeon-to-surgeon' about anatomy and flow.",
            behavioral_tendencies="Scrutinizes the 'Methods' section of clinical papers; relies heavily on peer validation from other high-volume centers.",
            thumbnail="Dr. Taylor Thorne",
            avatar_id="Graham_Chair_Sitting_public",
            created_by=current_user.email,
            last_updated_by=current_user.email
        )

        fields1 = [
            {
                "title_area": "Objective Completion",
                "rating": 10,
                "weight": 25,
                "comment": "To successfully master this area, the trainee needs to achieve the ideal sales outcome."
            },
            {
                "title_area": "Preparation & Product Knowledge",
                "rating": 10,
                "weight": 20,
                "comment": "GTo successfully master this area, the trainee needs to demonstrate knowledge of the product and its clinical evidence, as well as demonstrate that the customer's specific questions and concerns were effectively addressed."
            },
            {
                "title_area": "Demonstrating Value & Differentiation",
                "rating": 10,
                "weight": 15,
                "comment": "To successfully master this area, the trainee needs to demonstrate the unique product benefits and differentiation from competitors."
            },
            {
                "title_area": "Need Identification",
                "rating": 10,
                "weight": 10,
                "comment": "To successfully master this area, the trainee needs to uncover customer challenges through probing and active listening."
            },
            {
                "title_area": "Communication Clarity",
                "rating": 10,
                "weight": 10,
                "comment": "To successfully master this area, the trainee needs to demonstrate clarity, brevity, and persuasiveness in the messages delivered."
            },
            {
                "title_area": "Objection Handling",
                "rating": 10,
                "weight": 10,
                "comment": "To successfully master this area, the trainee needs to provide factual responses to concerns and demonstrate ability to resolve objections confidently."
            },
            {
                "title_area": "Closing & Next Steps",
                "rating": 10,
                "weight": 10,
                "comment": "To successfully master this area, the trainee needs to demonstrate that he/she asked for commitment and clarified next steps."
            }
        ]

        fields2 = [
            {
                "title_area": "Objective completion",
                "rating": 10,
                "weight": 25,
                "comment": "To successfully master this area, the trainee needs to achieve the ideal sales outcome."
            },
            {
                "title_area": "Preparation & Product Knowledge",
                "rating": 10,
                "weight": 10,
                "comment": "To successfully master this area, the trainee needs to demonstrate knowledge of the product and its clinical evidence, as well as demonstrate that the customer’s specific questions and concerns were effectively addressed."
            },
            {
                "title_area": "Demonstrating Value & Differentiation",
                "rating": 10,
                "weight": 20,
                "comment": "To successfully master this area, the trainee needs to demonstrate the unique product benefits and differentiation from competitors."
            },
            {
                "title_area": "Need Identification",
                "rating": 10,
                "weight": 10,
                "comment": "To successfully master this area, the trainee needs to uncover customer challenges through probing and active listening."
            },
            {
                "title_area": "Communication Clarity",
                "rating": 10,
                "weight": 10,
                "comment": "To successfully master this area, the trainee needs to demonstrate clarity, brevity, and persuasiveness in the messages delivered."
            },
            {
                "title_area": "Objection Handling",
                "rating": 10,
                "weight": 10,
                "comment": "To successfully master this area, the trainee needs to provide factual responses to concerns and demonstrate ability to resolve objections confidently."
            },
            {
                "title_area": "Closing & Next Steps",
                "rating": 10,
                "weight": 15,
                "comment": "To successfully master this area, the trainee needs to demonstrate that he/she asked for commitment and clarified next steps."
            }
        ]
        # Step 2: Create Evaluation related to the Persona
        evaluation1 = create_evaluation(
            session=db,
            title="Clinical ",
            description="Evaluates performance in highly clinical situations.",
            created_by=current_user.email,
            fields=fields1
        )

        evaluation2 = create_evaluation(
            session=db,
            title="Sales",
            description="Evaluates performance on helping your customer grow.",
            created_by=current_user.email,
            fields=fields2
        )

        # Step 3: Create Scenario related to Persona and Evaluation
        scenario1 = create_scenario(
            session=db,
            title="Evidence to Pilot: Winning Cath Lab Buy-In for a Breakthrough Therapy",
            scenario_image="default_samples/Image Scenario 1 catheter base device.png",
            description="Introduce breakthrough catheter therapy to evidence-driven cath lab director.",
            ai_trainer_opening="Win approval for a 60-day, 10-patient pilot with outcomes registry.",
            selling_methodology="Challenger",
            ideal_sales_outcome="Gets buy in to lead pilot: 10 cases, proctor coverage, defined indications, VBC/DRG analysis scheduled with value analysis committee",
            topics_to_cover="Evidence and peer validation; patient selection, contraindications, and complication mitigation; workflow, training, economics, and after-hours support.",
            current_state="Regional hospital, tight budget; peers split; administration cautious; legacy therapy standard; no device champions;",
            barriers_to_change="Comparable-population evidence gap; unclear cost/LOS/readmission impact; off-hours staffing and training burden.",
            critical_questions="What RCT/registry data mirrors our patients? Complication rates vs standard? Exact indications/contraindications? Cost per case and DRG impact? Proctoring and after-hours support?",
            persona_id=persona1.id,
            evaluation_id=evaluation1.id,
            created_by=current_user.email
        )

        scenario2 = create_scenario(
            session=db,
            title="From Wires to Wins: Proving Sternal Fixation at Scale",
            scenario_image="default_samples/Image Scenario 2 cardiac sternal fixation device.png",
            description="Present novel cardiac sternal fixation implant.",
            ai_trainer_opening="Secure 20-case pilot with STS endpoints.",
            selling_methodology="Challenger.",
            ideal_sales_outcome="Co-leads 20-case pilot with proctoring, perioperative bundle, STS/registry reporting, and Value Analysis pre-read.",
            topics_to_cover="Peer-validated outcomes; selection/contraindications; OR workflow, learning curve, VAC economics.",
            current_state="Wire standard; chronic pain complaints; throughput pressured; VAC cost-sensitive; team uncertain about on-call device support.",
            barriers_to_change="Evidence from high-volume centers; credible cost-offset/OR-time data; hands-on training with intraoperative fail-safes.",
            critical_questions="RCTs or registries mirroring our CABG/valve mix? Complication rates vs cerclage: infection, reoperation, pain? Exact indications/contraindications? OR time delta and cost-per-case? Proctoring and after-hours support?",
            persona_id=persona2.id,
            evaluation_id=evaluation2.id,
            created_by=current_user.email
        )

        # Step 4: Create Course related to the Scenario
        course1 = create_course(
            session=db,
            title="Compliance Course",
            audience="Sales Representatives",
            description="A course for advanced sales strategies and techniques",
            image_url="default_samples/compliance Course.png",
            course_file_url="default_samples/Compliance Course content.docx",
            created_by=current_user.id,
            instructor_id=current_user.id  # Example instructor ID
        )

        course2 = create_course(
            session=db,
            title="Challenger Sale Course",
            audience="Sales Representatives",
            description="A course for advanced sales strategies and techniques",
            image_url="default_samples/Challenger sale Image.webp",
            course_file_url="default_samples/CHallenger. sales for MedTech.docx",
            created_by=current_user.id,
            instructor_id=current_user.id  # Example instructor ID
        )

        # Commit all entities at the end
        db.commit()

        course1_file = course1.course_file_url
        course2_file = course2.course_file_url

        s3_client = await get_s3_client()
        course1_doc = await generate_presigned_url(s3_client, course1_file)
        course2_doc = await generate_presigned_url(s3_client, course2_file)
        
        await admin_coursefile_to_vectordb(course1.id, course1.title, db, current_user, course1_doc)
        await admin_coursefile_to_vectordb(course2.id, course2.title, db, current_user, course2_doc)

        logger.info(f"Successfully created Persona, Evaluation, Scenario, and Course!")

    except Exception as e:
        db.rollback()  # Rollback the transaction if an error occurs
        logger.error(f"Error: {str(e)}")
