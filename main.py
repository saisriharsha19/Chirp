# Lightweight Twitter Clone Backend
# Uses: FastAPI, SQLite, Argon2 for passwords, PyJWT for auth
# Install: pip install -r requirements.txt

from fastapi import FastAPI, HTTPException, Depends, File, UploadFile, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, Table, Boolean, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from datetime import datetime, timedelta
import jwt
import argon2
import os
import secrets
from typing import Optional, List
import json

# Lightweight database setup - SQLite
DATABASE_URL = "sqlite:///./twitter_clone.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# JWT settings
SECRET_KEY = secrets.token_hex(32)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Password hasher
ph = argon2.PasswordHasher()

# Database Models (optimized for minimal storage)
followers_table = Table(
    'followers', Base.metadata,
    Column('follower_id', Integer, ForeignKey('users.id'), primary_key=True),
    Column('followed_id', Integer, ForeignKey('users.id'), primary_key=True)
)

likes_table = Table(
    'likes', Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id'), primary_key=True),
    Column('tweet_id', Integer, ForeignKey('tweets.id'), primary_key=True)
)

bookmarks_table = Table(
    'bookmarks', Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id'), primary_key=True),
    Column('tweet_id', Integer, ForeignKey('tweets.id'), primary_key=True)
)

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True)
    email = Column(String(100), unique=True, index=True)
    password_hash = Column(String(128))
    bio = Column(String(160), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Unique features
    mood = Column(String(20), default="neutral")  # Current mood indicator
    activity_score = Column(Float, default=0.0)  # Activity score based on engagement
    is_verified = Column(Boolean, default=False)  # Verification status
    
    tweets = relationship("Tweet", back_populates="author", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="author", cascade="all, delete-orphan")
    
    followers = relationship(
        "User",
        secondary=followers_table,
        primaryjoin=id == followers_table.c.followed_id,
        secondaryjoin=id == followers_table.c.follower_id,
        backref="following"
    )
    
    liked_tweets = relationship("Tweet", secondary=likes_table, backref="liked_by")
    bookmarked_tweets = relationship("Tweet", secondary=bookmarks_table, backref="bookmarked_by")

class Tweet(Base):
    __tablename__ = "tweets"
    
    id = Column(Integer, primary_key=True, index=True)
    content = Column(String(280))  # Twitter's character limit
    author_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Unique features
    sentiment = Column(String(20), default="neutral")  # Auto-detected sentiment
    is_ephemeral = Column(Boolean, default=False)  # Disappearing tweets
    ephemeral_duration = Column(Integer, default=24)  # Hours before deletion
    thread_id = Column(Integer, ForeignKey("tweets.id"), nullable=True)  # Thread support
    
    author = relationship("User", back_populates="tweets")
    comments = relationship("Comment", back_populates="tweet", cascade="all, delete-orphan")
    thread_replies = relationship("Tweet", backref="parent_tweet", remote_side=[id])

class Comment(Base):
    __tablename__ = "comments"
    
    id = Column(Integer, primary_key=True, index=True)
    content = Column(String(280))
    author_id = Column(Integer, ForeignKey("users.id"))
    tweet_id = Column(Integer, ForeignKey("tweets.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    author = relationship("User", back_populates="comments")
    tweet = relationship("Tweet", back_populates="comments")

# Pydantic models for request/response
class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    bio: Optional[str] = ""

class UserLogin(BaseModel):
    username: str
    password: str

class TweetCreate(BaseModel):
    content: str
    is_ephemeral: Optional[bool] = False
    ephemeral_duration: Optional[int] = 24
    thread_id: Optional[int] = None

class CommentCreate(BaseModel):
    content: str
    tweet_id: int

class UserUpdate(BaseModel):
    bio: Optional[str] = None
    mood: Optional[str] = None

# Database initialization
Base.metadata.create_all(bind=engine)

# FastAPI app
app = FastAPI(title="Lightweight Twitter Clone")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# JWT token creation
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# Get current user from token
def get_current_user(authorization: str = Header(None), db: Session = Depends(get_db)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    
    try:
        # Remove 'Bearer ' prefix if present
        token = authorization
        if token.startswith('Bearer '):
            token = token[7:]
            
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# Simple sentiment analysis (can be replaced with ML model)
from transformers import AutoTokenizer, AutoModelForSequenceClassification, pipeline

model_name = "cardiffnlp/twitter-roberta-base-sentiment-latest"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForSequenceClassification.from_pretrained(model_name)
sentiment_pipeline = pipeline("sentiment-analysis", model=model, tokenizer=tokenizer)
def analyze_sentiment(text: str) -> str:
    result = sentiment_pipeline(text)[0]
    return result['label'].lower()


# Update activity score
def update_activity_score(user: User, db: Session, points: float):
    user.activity_score += points
    db.commit()

# API Endpoints

@app.post("/api/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    # Check if user exists
    if db.query(User).filter(User.username == user.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    if db.query(User).filter(User.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email already exists")
    
    # Create user
    db_user = User(
        username=user.username,
        email=user.email,
        password_hash=ph.hash(user.password),
        bio=user.bio
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    # Create token
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer", "user_id": db_user.id}

@app.post("/api/login")
def login(user: UserLogin, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if not db_user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    try:
        ph.verify(db_user.password_hash, user.password)
    except:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer", "user_id": db_user.id}

@app.get("/api/user/{user_id}")
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "id": user.id,
        "username": user.username,
        "bio": user.bio,
        "mood": user.mood,
        "activity_score": user.activity_score,
        "is_verified": user.is_verified,
        "created_at": user.created_at,
        "followers_count": len(user.followers),
        "following_count": len(user.following)
    }

@app.put("/api/user/update")
def update_user(update: UserUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if update.bio is not None:
        current_user.bio = update.bio[:160]  # Limit bio length
    if update.mood is not None:
        current_user.mood = update.mood
    
    db.commit()
    return {"message": "User updated successfully"}

@app.post("/api/tweet")
def create_tweet(tweet: TweetCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Analyze sentiment
    sentiment = analyze_sentiment(tweet.content)
    
    # Create tweet
    db_tweet = Tweet(
        content=tweet.content[:280],  # Enforce character limit
        author_id=current_user.id,
        sentiment=sentiment,
        is_ephemeral=tweet.is_ephemeral,
        ephemeral_duration=tweet.ephemeral_duration,
        thread_id=tweet.thread_id
    )
    db.add(db_tweet)
    db.commit()
    db.refresh(db_tweet)
    
    # Update activity score
    update_activity_score(current_user, db, 1.0)
    
    return {
        "id": db_tweet.id,
        "content": db_tweet.content,
        "author": current_user.username,
        "created_at": db_tweet.created_at,
        "sentiment": db_tweet.sentiment,
        "is_ephemeral": db_tweet.is_ephemeral
    }

@app.get("/api/tweets")
def get_tweets(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    # Clean up ephemeral tweets
    expired_tweets = db.query(Tweet).filter(
        Tweet.is_ephemeral == True,
        Tweet.created_at < datetime.utcnow() - timedelta(hours=24)
    ).all()
    for tweet in expired_tweets:
        db.delete(tweet)
    db.commit()
    
    # Get tweets
    tweets = db.query(Tweet).order_by(Tweet.created_at.desc()).offset(skip).limit(limit).all()
    
    return [{
        "id": tweet.id,
        "content": tweet.content,
        "author": tweet.author.username,
        "author_id": tweet.author_id,
        "created_at": tweet.created_at,
        "sentiment": tweet.sentiment,
        "is_ephemeral": tweet.is_ephemeral,
        "likes_count": len(tweet.liked_by),
        "comments_count": len(tweet.comments),
        "is_verified": tweet.author.is_verified
    } for tweet in tweets]

@app.get("/api/tweet/{tweet_id}")
def get_tweet(tweet_id: int, db: Session = Depends(get_db)):
    tweet = db.query(Tweet).filter(Tweet.id == tweet_id).first()
    if not tweet:
        raise HTTPException(status_code=404, detail="Tweet not found")
    
    return {
        "id": tweet.id,
        "content": tweet.content,
        "author": tweet.author.username,
        "author_id": tweet.author_id,
        "created_at": tweet.created_at,
        "sentiment": tweet.sentiment,
        "likes_count": len(tweet.liked_by),
        "comments": [{
            "id": comment.id,
            "content": comment.content,
            "author": comment.author.username,
            "created_at": comment.created_at
        } for comment in tweet.comments]
    }

@app.post("/api/comment")
def create_comment(comment: CommentCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Check if tweet exists
    tweet = db.query(Tweet).filter(Tweet.id == comment.tweet_id).first()
    if not tweet:
        raise HTTPException(status_code=404, detail="Tweet not found")
    
    # Create comment
    db_comment = Comment(
        content=comment.content[:280],
        author_id=current_user.id,
        tweet_id=comment.tweet_id
    )
    db.add(db_comment)
    db.commit()
    
    # Update activity score
    update_activity_score(current_user, db, 0.5)
    
    return {"message": "Comment created successfully"}

@app.post("/api/tweet/{tweet_id}/like")
def like_tweet(tweet_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tweet = db.query(Tweet).filter(Tweet.id == tweet_id).first()
    
    if not tweet:
        raise HTTPException(status_code=404, detail="Tweet not found")
    
    if tweet in current_user.liked_tweets:
        current_user.liked_tweets.remove(tweet)
        update_activity_score(current_user, db, -0.2)
        message = "Tweet unliked"
    else:
        current_user.liked_tweets.append(tweet)
        update_activity_score(current_user, db, 0.2)
        message = "Tweet liked"
    
    db.commit()
    return {"message": message}

@app.post("/api/tweet/{tweet_id}/bookmark")
def bookmark_tweet(tweet_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tweet = db.query(Tweet).filter(Tweet.id == tweet_id).first()
    
    if not tweet:
        raise HTTPException(status_code=404, detail="Tweet not found")
    
    if tweet in current_user.bookmarked_tweets:
        current_user.bookmarked_tweets.remove(tweet)
        message = "Bookmark removed"
    else:
        current_user.bookmarked_tweets.append(tweet)
        message = "Tweet bookmarked"
    
    db.commit()
    return {"message": message}

@app.post("/api/user/{user_id}/follow")
def follow_user(user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user_to_follow = db.query(User).filter(User.id == user_id).first()
    
    if not user_to_follow:
        raise HTTPException(status_code=404, detail="User not found")
    
    if user_to_follow == current_user:
        raise HTTPException(status_code=400, detail="Cannot follow yourself")
    
    if user_to_follow in current_user.following:
        current_user.following.remove(user_to_follow)
        update_activity_score(current_user, db, -0.5)
        message = "Unfollowed user"
    else:
        current_user.following.append(user_to_follow)
        update_activity_score(current_user, db, 0.5)
        message = "Following user"
    
    db.commit()
    return {"message": message}

@app.get("/api/user/{user_id}/tweets")
def get_user_tweets(user_id: int, skip: int = 0, limit: int = 20, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    tweets = db.query(Tweet).filter(Tweet.author_id == user_id).order_by(
        Tweet.created_at.desc()
    ).offset(skip).limit(limit).all()
    
    return [{
        "id": tweet.id,
        "content": tweet.content,
        "created_at": tweet.created_at,
        "sentiment": tweet.sentiment,
        "likes_count": len(tweet.liked_by),
        "comments_count": len(tweet.comments)
    } for tweet in tweets]

@app.get("/api/feed")
def get_feed(skip: int = 0, limit: int = 20, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Get tweets from followed users and self
    followed_ids = [u.id for u in current_user.following] + [current_user.id]
    
    tweets = db.query(Tweet).filter(
        Tweet.author_id.in_(followed_ids)
    ).order_by(Tweet.created_at.desc()).offset(skip).limit(limit).all()
    
    return [{
        "id": tweet.id,
        "content": tweet.content,
        "author": tweet.author.username,
        "author_id": tweet.author_id,
        "created_at": tweet.created_at,
        "sentiment": tweet.sentiment,
        "likes_count": len(tweet.liked_by),
        "comments_count": len(tweet.comments),
        "is_verified": tweet.author.is_verified
    } for tweet in tweets]

@app.get("/api/trending")
def get_trending(db: Session = Depends(get_db)):
    # Get most liked tweets from last 24 hours
    yesterday = datetime.utcnow() - timedelta(days=1)
    
    tweets = db.query(Tweet).filter(
        Tweet.created_at > yesterday
    ).all()
    
    # Sort by engagement (likes + comments)
    trending = sorted(tweets, key=lambda t: len(t.liked_by) + len(t.comments), reverse=True)[:10]
    
    return [{
        "id": tweet.id,
        "content": tweet.content,
        "author": tweet.author.username,
        "engagement": len(tweet.liked_by) + len(tweet.comments)
    } for tweet in trending]

@app.get("/api/search")
def search(q: str, db: Session = Depends(get_db)):
    # Search tweets
    tweets = db.query(Tweet).filter(
        Tweet.content.contains(q)
    ).limit(20).all()
    
    # Search users
    users = db.query(User).filter(
        User.username.contains(q)
    ).limit(10).all()
    
    return {
        "tweets": [{
            "id": tweet.id,
            "content": tweet.content,
            "author": tweet.author.username,
            "created_at": tweet.created_at
        } for tweet in tweets],
        "users": [{
            "id": user.id,
            "username": user.username,
            "bio": user.bio,
            "is_verified": user.is_verified
        } for user in users]
    }

# Serve static files (for frontend)
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)