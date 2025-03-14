from __future__ import unicode_literals

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
# Used to create and manually log in a user
from django.contrib.auth.models import User
from django.contrib.auth import login, authenticate
from a2chatbot.models import *
from django.views.decorators.csrf import ensure_csrf_cookie
from django.contrib.auth.models import User
from django.http import HttpResponse, Http404, JsonResponse
from django.core.files import File
from django.utils import timezone

from openai import OpenAI
import os
import re
import json
import csv
import threading

# include the api key 
client = OpenAI(api_key = '')
topic = 'mutation'
question = "What is compound interest?"

global_vector_store_id = None
global_assistant_id = None
global_file_ids = []

questions_list = [
    "What is compound interest?",
    "How does inflation affect the economy?",
    "What are the key differences between a savings account and an investment account?",
    "What factors determine your credit score?",
    "What’s the difference between stocks and bonds?",
    "Why is diversification important in investing?",
    "When is the best time to start saving for retirement?",
    "How do taxes impact personal finance?"
]

question_keywords = {
    "What is compound interest?": {"keywords": ["interest", "principal", "compounding", "growth", "rate", "investment"], "threshold": 3},
    "How does inflation affect the economy?": {"keywords": ["inflation", "prices", "purchasing power", "economy", "money supply", "wages"], "threshold": 2},
    "What are the key differences between a savings account and an investment account?": {"keywords": ["savings", "investment", "returns", "liquidity", "risk", "growth"], "threshold": 2},
    "What factors determine your credit score?": {"keywords": ["credit", "score", "payment history", "debt", "utilization", "length of credit"], "threshold": 2},
    "What’s the difference between stocks and bonds?": {"keywords": ["stocks", "bonds", "ownership", "debt", "dividends", "interest"], "threshold": 2},
    "Why is diversification important in investing?": {"keywords": ["diversification", "risk", "portfolio", "investments", "allocation"], "threshold": 2},
    "When is the best time to start saving for retirement?": {"keywords": ["retirement", "early", "401k", "IRA", "compound", "savings"], "threshold": 1},
    "How do taxes impact personal finance?": {"keywords": ["taxes", "income", "deductions", "brackets", "credits", "capital gains"], "threshold": 1}
}

userid_list = ['student1', 'student2']
history_text = "What is compound interest?"


@ensure_csrf_cookie
@login_required
def home(request):
    print("homehome")
    context = {}
    user = request.user

    # Clear any existing assistant if needed
    if Assistant.objects.filter(user=user, video_name=topic).exists():
        assistant = get_object_or_404(Assistant, user=user, video_name=topic)
        assistant.delete()

    # Reset the session data
    Message.objects.filter(conversation_id=str(user.id)).delete()
    request.session["current_question_index"] = 0
    request.session["matched_keywords"] = {}
    history_text = "What is compound interest?"

    participant = get_object_or_404(Participant, user=user)
    context['user'] = user
    print(user.username)

    # Create a new assistant if it does not already exist
    if not Assistant.objects.filter(user=user, video_name=topic).exists():
        # print("[Debug] Initializing assistant for user:", user.username)
        initialize_assistant(user)
    context = {"user": user, "question": question}
    return render(request, 'a2chatbot/welcome.html', context)
@login_required
def sendmessage(request):
    print("sendmessage")
    user = request.user
    if request.method == "POST":
        print(request.POST)
        context = {}
        studentmessage = request.POST["message"]

        # Record the student's message in the conversation
        Message.objects.create(
            conversation_id=str(user.id),
            sender="user",
            content=studentmessage,
            timestamp=timezone.now()
        )

        assistant = get_object_or_404(Assistant, user=user, video_name=topic)

        # Retrieve the current question based on the session's question index
        current_question_index = request.session.get("current_question_index", 0)
        current_question = questions_list[current_question_index]

        # Get conversation history for context in the AI response
        conversation_history = Message.objects.filter(conversation_id=str(user.id)).order_by('timestamp')
        history_text = "\n".join([f"{msg.sender}: {msg.content}" for msg in conversation_history])

        # Initialize prompt in case it’s not set in the following logic
        prompt = ""

        # Check if the student has met the understanding threshold for the current question
        if check_understanding(request, studentmessage, current_question):
            # Move to the next question if the student demonstrated understanding
            next_question_index = current_question_index + 1

            if user.username == "student2" and not request.session.get("follow_up_asked", False):
                # Set the session to indicate that a follow-up question has been asked
                request.session["follow_up_asked"] = True

                # Provide a follow-up question for Student2 before moving to the next main question
                follow_up_prompt = f"""Here is the conversation history:\n\n{history_text}\n\n
                Based on this, the user (Student2) has demonstrated understanding of the question: "{current_question}".
                However, as they are an advanced learner, please ask one **follow-up advanced financial question** to deepen their knowledge before moving to the next topic.
                The follow-up question should focus on **real-world financial applications, investment strategies, or advanced financial planning concepts**."""

                prompt = f"""You are a financial literacy expert guiding an advanced learner named Student2.
                            Student2 already understands the basics of personal finance and is interested in more **complex financial topics**.
                            Please respond with a **follow-up question** that challenges them to think critically about advanced financial concepts.

                            {follow_up_prompt}"""

            else:
                next_question_index = current_question_index + 1
                # Reset follow-up status and proceed to the next question
                request.session["follow_up_asked"] = False  # Reset the follow-up flag
                if next_question_index < len(questions_list):
                    next_question = questions_list[next_question_index]
                    request.session["current_question_index"] = next_question_index
                    prompt = f"""You are a supportive financial education assistant. Based on the conversation history below, the user has demonstrated understanding of the question: "{current_question}".
                    Please move to the next question: "{next_question}".

                    Conversation history:
                    {history_text}"""
                else:
                    # If no more questions, end the conversation and delete the assistant
                    delete_agent(user)
                    return JsonResponse({"status": "Great job! You have completed all financial literacy questions."})

                    else:
                        # Provide a hint based on keywords if the student needs further help
                        keywords = question_keywords.get(current_question, {}).get("keywords", [])
                        student_persona = user.username  # Determine the persona based on username

                        # Construct a fill-in-the-blank hint message using the keywords
                        if keywords:
                            if student_persona == "student1":
                                # Simpler hint for beginner persona
                                hint_message = f"Something similar to the format, Think of a word that means a ' ____' related to {keywords[0]} or {keywords[1]}. Try to fill in the blank!"
                            elif student_persona == "student2":
                                # More complex hint for advanced persona
                                hint_message = f"Consider how a '____ in {keywords[0]}' could affect traits like {keywords[1]}. Try to fill in the blank with the right term."
                        else:
                            # General hint if no specific keywords are found
                            hint_message = "Try to think carefully about the question and respond."

                        # Generate the prompt with the hint message included
                        prompt = f"""Here is the conversation history:\n\n{history_text}\n\n
                        The student is still struggling with the question: "{current_question}".
                        Please provide a hint or follow-up question that encourages understanding.
                        If the user is {user.username} is student1, consider giving a hint.
                        If the student is asking a question, try giving a hint message with fill in the blank problem. (Do not indicate as fill-in the blank just show them)
                        Consider giving a hint: For example {hint_message} like this, but do not give the full keywords to the student. This is just an example, make your own blank in terms of the question
                        """

        # Send the prompt to the assistant
        thread = client.beta.threads.create(
            messages=[
                {
                    "role": "user",
                    "content": f"""You are a financial education assistant, helping users understand concepts related to personal finance, investing, and banking.

                    To facilitate the user's active learning,
                    you asked them an initial open-ended question: "{question}",
                    now your goal is to guide the conversation based on the user's response: "{studentmessage}".

                    Now, based on the user’s response, please assess their level of understanding.
                    - If they seem unsure, simplify the explanation and provide key financial terms.
                    - If they are correct, confirm their response and encourage deeper financial insights.
                    - If they ask for clarification, provide a breakdown of the concept in easy-to-understand terms.
                    
                    When responding to the user’s message, format the response professionally:
                    - Highlight key financial terms and concepts.
                    - Use bullet points to summarize important takeaways.
                    - Make responses concise and to the point.

                    Please respond with only **one message** at a time. Your goal is to:
                    - Ask a follow-up question if the user’s response indicates partial understanding.
                    - Provide hints or examples related to real-world finance if they need more help.
                    - Encourage deeper thinking by introducing advanced financial concepts when applicable.
                    - Keep a supportive and educational tone, making finance approachable and engaging.
                    
                    When providing answers:
                    - Use simple, clear explanations.
                    - Relate financial concepts to practical scenarios (e.g., budgeting, credit scores, investments).
                    - If the user struggles, guide them step by step with examples.
                    
                    {prompt}"""
                }
            ]
        )

        run = client.beta.threads.runs.create_and_poll(thread_id=thread.id, assistant_id=assistant.assistant_id, temperature=0.56)
        messages = list(client.beta.threads.messages.list(thread_id=thread.id, run_id=run.id))
        message_content = messages[0].content[0].text

        # Record the assistant's response in the conversation
        Message.objects.create(
            conversation_id=str(user.id),
            sender="assistant",
            content=message_content.value,
            timestamp=timezone.now()
        )
        
        print("Conversation History:\n", history_text)
        
        response_text = []
        response_text.append({'bot_message': message_content.value})
        response = json.dumps(response_text)
        return HttpResponse(response, 'application/javascript')


def check_understanding(request, student_response, question):
    question_data = question_keywords.get(question, {})
    keywords = question_data.get("keywords", [])
    threshold = question_data.get("threshold", 1)

    # Convert the student response to lowercase for case-insensitive matching
    student_response = student_response.lower()

    # Initialize matched_keywords as a dictionary with the question as the key
    if "matched_keywords" not in request.session:
        request.session["matched_keywords"] = {}
    if question not in request.session["matched_keywords"]:
        request.session["matched_keywords"][question] = []  # Use a list instead of a set

    # Iterate through each keyword and check if it's in the student response
    for keyword in keywords:
        if keyword in student_response and keyword not in request.session["matched_keywords"][question]:
            request.session["matched_keywords"][question].append(keyword)
        
    # Convert the list back to a set temporarily to count unique matched keywords
    matched_keywords_set = set(request.session["matched_keywords"][question])
    score = len(matched_keywords_set)
    
    # Save the updated matched keywords set back to the session as a list
    request.session["matched_keywords"][question] = list(matched_keywords_set)
    request.session.modified = True

    # print(f"[Debug] Matched Keywords for '{question}': {matched_keywords_set}")
    # print(f"[Debug] Keywords matched count: {score}, Required threshold: {threshold}")

    return score >= threshold  # Returns True if score meets or exceeds threshold

def initialize_assistant(user):
    global global_vector_store_id, global_assistant_id, global_file_ids
    if user.username == "student1":
        instructions = """
        You are a friendly and approachable middle school science tutor helping a curious beginner student named Student1. 
        Student1 is eager to learn the basics about mutations, so focus on simple explanations, encouragement, 
        and relatable examples to build a strong foundational understanding.
        """
    elif user.username == "student2":
        instructions = """
        You are a knowledgeable  middle school science tutor guiding an advanced student named Student2. 
        Student2 already understands the basics of mutations and is interested in more complex topics, 
        such as the molecular mechanisms and real-world applications. Provide deeper explanations and 
        encourage critical thinking.
        """
    else:
        instructions = """
        You are a middle school science tutor. Provide explanations based on the student's level of understanding.
        """
        
    assistant = client.beta.assistants.create(
        name=f"{user.username}'s Science Tutor",
        instructions=instructions,
        model="gpt-4o",
        temperature=0,
        tools=[{"type": "file_search"}],
    )

    vector_store = client.beta.vector_stores.create(name="video transcripts")
    file = client.files.create(file=open('mutation.txt', 'rb'), purpose='assistants')
    file_batch = client.beta.vector_stores.files.create(vector_store_id=vector_store.id, file_id=file.id)
	
	# Set the global variables
    global_vector_store_id = vector_store.id
    global_assistant_id = assistant.id
    global_file_ids = [file.id]

    # Update assistant with file resources
    client.beta.assistants.update(
        assistant_id=assistant.id,
        tool_resources={"file_search": {"vector_store_ids": [vector_store.id]}}
    )

    # Save the assistant in the database
    new_assistant = Assistant(
        video_name=topic,
        assistant_id=assistant.id,
        vector_store_id=vector_store.id,
        user=user
    )
    new_assistant.save()


def delete_agent(user):
    global global_vector_store_id, global_assistant_id, global_file_ids

    try:
        # Delete files associated with the vector store
        for file_id in global_file_ids:
            if file_id:
                client.beta.vector_stores.files.delete(vector_store_id=global_vector_store_id, file_id=file_id)
                client.files.delete(file_id)

        # Delete the vector store and assistant
        client.beta.vector_stores.delete(global_vector_store_id)
        client.beta.assistants.delete(global_assistant_id)

        # Clear Assistant instance in database
        assistant = get_object_or_404(Assistant, user=user, video_name=topic)
        assistant.delete()
    except Exception as e:
        print(f"[Error] Failed to delete resources: {e}")
    
@login_required
def end_conversation(request):
    user = request.user
    delete_agent(user)
    return JsonResponse({"status": "Conversation and assistant resources deleted successfully"})

def register_new_users():
	for i in range(len(userid_list)):
		user= User.objects.create_user(username=userid_list[i], password = userid_list[i])
		user.save()        
		participant = Participant(user = user)
		participant.save()
	print("new users registered")
