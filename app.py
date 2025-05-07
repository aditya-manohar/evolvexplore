# app.py
from flask import Flask, render_template, request, jsonify
import requests
from datetime import datetime
import time
import random
import urllib.parse
import os
from bs4 import BeautifulSoup
import nltk
from nltk.corpus import wordnet
from random import choice, random
from project_ideas import PROJECT_IDEAS

app = Flask(__name__)

app.config['DEBUG'] = True      
app.config['TEMPLATES_AUTO_RELOAD'] = True

# API Keys
CORE_API_KEY = 'Wul8QFhyPUK7MjRvC06HJoTYf2AaqDBe'
SERPAPI_KEY = 'b8dd20a4fc927ceb6d8e0283435af5f05abb71a82f263c47eefffacadcd2e726'

# Simple cache with timeout
cache = {
    'papers': {},
    'code': {},
    'ppts': {},
    'datasets': {},
    'timelines': {},
    'last_cleared': time.time()
}

nltk.download('wordnet', download_dir='./nltk_data/')  # ~10MB download
nltk.download('omw-1.4', download_dir='./nltk_data/')  # ~1MB
nltk.data.path.append('./nltk_data/')

def clear_old_cache():
    """Clear cache entries older than 1 hour"""
    current_time = time.time()
    if current_time - cache['last_cleared'] > 3600:  
        for cache_type in ['papers', 'code', 'ppts', 'datasets', 'timelines']:
            cache[cache_type] = {}
        cache['last_cleared'] = current_time

@app.before_request
def before_request():
    clear_old_cache()

def fetch_core_papers(query):
    """Fetch papers from CORE.ac.uk API"""
    try:
        url = "https://api.core.ac.uk/v3/search/works"
        params = {
            'q': query,
            'limit': 20,
            'apiKey': CORE_API_KEY
        }
        headers = {'Authorization': f'Bearer {CORE_API_KEY}'}
        
        response = requests.get(url, params=params, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        papers = []
        for result in data.get('results', []):
            pdf_link = ''
            if result.get('downloadUrl'):
                pdf_link = result['downloadUrl']
            elif result.get('fullTextIdentifier'):
                pdf_link = result['fullTextIdentifier']
            
            papers.append({
                "title": result.get('title', 'No title available'),
                "summary": result.get('abstract', 'No abstract available')[:500] + '...',
                "link": result.get('doiUrl', result.get('url', '#')),
                "pdf_link": pdf_link,
                "source": "CORE.ac.uk",
                "published": result.get('publishedDate', 'Date not available'),
                "authors": ', '.join(author['name'] for author in result.get('authors', [])[:3]),
                "direct_pdf": bool(pdf_link)
            })
        return papers
    except Exception as e:
        print(f"CORE.ac.uk API error: {str(e)}")
        return []

def fetch_scholar_results(query):
    try:
        # Replace with this API-based approach
        api_url = "https://serpapi.com/search.json"
        params = {
            'engine': 'google_scholar',
            'q': query,
            'api_key': SERPAPI_KEY, 
            'num': 20
        }
        response = requests.get(api_url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        papers = []
        for result in data.get('organic_results', []):
            papers.append({
                "title": result.get('title'),
                "summary": result.get('snippet', ''),
                "link": result.get('link', '#'),
                "pdf_link": result.get('inline_links', {}).get('pdf', {}).get('link', ''),
                "source": "Google Scholar",
                "published": result.get('publication_info', {}).get('summary', 'Date not available'),
                "direct_pdf": bool(result.get('inline_links', {}).get('pdf', {}).get('link'))
            })
        return papers
    except Exception as e:
        print(f"Scholar API error: {str(e)}")
        return []

def fetch_papers(query):
    try:
        if query in cache['papers']:
            return cache['papers'][query]
        
        papers = []

        # Fetch from CORE.ac.uk first
        core_papers = fetch_core_papers(query)
        papers.extend(core_papers)
        
        # Then fetch from Google Scholar
        scholar_papers = fetch_scholar_results(query)
        papers.extend(scholar_papers)
        
        # 1. Fetch arXiv papers
        arxiv_url = f"http://export.arxiv.org/api/query?search_query=all:{query}&max_results=50"
        try:
            response = requests.get(arxiv_url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml-xml')
            for entry in soup.find_all('entry'):
                papers.append({
                    "title": entry.title.text.strip(),
                    "summary": entry.summary.text.strip(),
                    "link": entry.id.text,
                    "pdf_link": entry.id.text.replace('abs', 'pdf') + ".pdf",
                    "source": "arXiv",
                    "published": datetime.strptime(entry.published.text, '%Y-%m-%dT%H:%M:%SZ').strftime('%b %d, %Y'),
                    "has_pdf": True,
                    "direct_pdf": True  
                })
        except Exception as e:
            print(f"Error fetching arXiv papers: {str(e)}")
        
        # 3. Semantic Scholar (optional - keep if you want)
        sem_scholar_url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={query}&limit=50"
        try:
            response = requests.get(sem_scholar_url, timeout=15)
            response.raise_for_status()
            for paper in response.json().get('data', [])[:5]:
                if 'title' in paper and 'paperId' in paper:
                    pdf_link = paper.get('openAccessPdf', {}).get('url', '')
                    papers.append({
                        "title": paper['title'],
                        "summary": paper.get('abstract', 'No abstract available'),
                        "link": f"https://www.semanticscholar.org/paper/{paper['paperId']}",
                        "pdf_link": pdf_link,
                        "source": "Semantic Scholar",
                        "published": f"Year: {paper['year']}" if paper.get('year') else "Date not available",
                        "has_pdf": bool(pdf_link),
                        "direct_pdf": bool(pdf_link) 
                    })
        except Exception as e:
            print(f"Error fetching Semantic Scholar papers: {str(e)}")
        
        # Remove duplicates by title
        seen_titles = set()
        unique_papers = []
        for paper in papers:
            title = paper['title'].lower().strip()
            if title not in seen_titles:
                seen_titles.add(title)
                unique_papers.append(paper)
        
        cache['papers'][query] = unique_papers
        return unique_papers
    
    except Exception as e:
        print(f"General error fetching papers: {str(e)}")
        return []

def fetch_code(query):
    try:
        if query in cache['code']:
            return cache['code'][query]
        
        url = f"https://api.github.com/search/repositories?q={query}&sort=stars&order=desc"
        headers = {"Accept": "application/vnd.github.v3+json"}
        response = requests.get(url, headers=headers, timeout=10)
        code = []
        
        if response.status_code == 200:
            for repo in response.json()['items'][:30]:
                code.append({
                    "name": repo['name'],
                    "description": repo['description'] or "No description",
                    "url": repo['html_url'],
                    "stars": repo['stargazers_count'],
                    "language": repo['language'] or "Not specified",
                    "last_updated": datetime.strptime(repo['updated_at'], '%Y-%m-%dT%H:%M:%SZ').strftime('%b %d, %Y')
                })
        
        cache['code'][query] = code
        return code
    
    except Exception as e:
        print(f"Error fetching code: {e}")
        return []

def fetch_ppts(query):
    try:
        if query in cache['ppts']:
            return cache['ppts'][query]
        
        ppts = []
        
        # SlideShare search
        slideshare_url = f"https://www.slideshare.net/search/slideshow?searchfrom=header&q={urllib.parse.quote(query)}"
        ppts.append({
            "title": f"SlideShare presentations for {query}",
            "description": "Professional academic presentations from SlideShare",
            "link": slideshare_url,
            "source": "SlideShare",
            "thumbnail": "https://cdn-icons-png.flaticon.com/512/281/281760.png"
        })
        
        # Academia.edu PPT search
        academia_url = f"https://www.academia.edu/search?q={urllib.parse.quote(query.replace(' ', '-'))}"
        ppts.append({
            "title": f"Academic PPTs for {query}",
            "description": "Presentations shared by researchers and professors",
            "link": academia_url,
            "source": "Academia.edu",
            "thumbnail": "https://cdn.academia.edu/favicon.ico"
        })
        
        # ResearchGate presentations
        researchgate_url = f"https://www.researchgate.net/search/publication?q={urllib.parse.quote(query)}&documentType=presentation"
        ppts.append({
            "title": f"Research presentations for {query}",
            "description": "Conference and research presentations from ResearchGate",
            "link": researchgate_url,
            "source": "ResearchGate",
            "thumbnail": "https://www.researchgate.net/favicon.ico"
        })
        
        # MIT OpenCourseWare presentations
        mit_url = f"https://ocw.mit.edu/search/?q={urllib.parse.quote(query)}&d=LectureNotes"
        ppts.append({
            "title": f"MIT Course presentations for {query}",
            "description": "Lecture slides from MIT OpenCourseWare",
            "link": mit_url,
            "source": "MIT OCW",
            "thumbnail": "https://ocw.mit.edu/favicon.ico"
        })
        
        cache['ppts'][query] = ppts
        return ppts
    
    except Exception as e:
        print(f"Error fetching PPTs: {e}")
        return []

def fetch_datasets(query):
    try:
        if query in cache['datasets']:
            return cache['datasets'][query]
        
        # Properly encode the query for Kaggle (spaces become +)
        kaggle_search_query = query.replace(' ', '+')
        kaggle_url = f"https://www.kaggle.com/datasets?search={kaggle_search_query}"
        
        # Create datasets list with just the search link
        datasets = [
            {
                "title": f"Kaggle Datasets: {query}",
                "description": f"Search for '{query}' datasets on Kaggle",
                "link": kaggle_url,
                "download_link": kaggle_url,
                "source": "Kaggle",
                "size": "Varies",
                "license": "Varies",
                "student_friendly": True,
                "direct_download": False,
                "thumbnail": "https://cdn4.iconfinder.com/data/icons/logos-and-brands/512/189_Kaggle_logo_logos-512.png"
            }
        ]
        
        # Add other dataset sources
        essential_datasets = [
            {
                "title": "Kaggle Datasets",
                "description": "Thousands of free datasets across all domains (AI, healthcare, finance, etc.)",
                "link": f"https://www.kaggle.com/datasets?search={urllib.parse.quote(query)}",
                "source": "Kaggle",
                "student_friendly": True,
                "thumbnail": "https://cdn4.iconfinder.com/data/icons/logos-and-brands/512/189_Kaggle_logo_logos-512.png"
            },
            {
                "title": "UCI Machine Learning Repo",
                "description": "300+ classic datasets for ML (iris, wine, spam, etc.)",
                "link": f"https://archive.ics.uci.edu/ml/index.php?search={urllib.parse.quote(query)}",
                "source": "UCI",
                "student_friendly": True,
                "thumbnail": "https://archive.ics.uci.edu/ml/assets/logo.jpg"
            },
            {
                "title": "Google Dataset Search",
                "description": "Search engine for 25M+ public datasets",
                "link": f"https://datasetsearch.research.google.com/search?query={urllib.parse.quote(query)}",
                "source": "Google",
                "student_friendly": True,
                "thumbnail": "https://www.gstatic.com/images/branding/product/1x/dataset_search_48dp.png"
            },
            {
                "title": "Data.gov (US Government)",
                "description": "250K+ datasets (census, transportation, energy)",
                "link": f"https://catalog.data.gov/dataset/?q={urllib.parse.quote(query)}",
                "source": "US Gov",
                "student_friendly": True,
                "thumbnail": "https://www.data.gov/app/uploads/2020/12/cropped-data-gov-favicon-32x32.png"
            },
            {
                "title": "NASA Open Data",
                "description": "Space, climate, and satellite datasets",    
                "link": f"https://data.nasa.gov/dataset/?q={urllib.parse.quote(query)}",
                "source": "NASA",
                "student_friendly": True,
                "thumbnail": "https://www.nasa.gov/wp-content/themes/nasa/assets/images/favicon.ico"
            },
             {
                "title": "EU Open Data Portal",
                "description": "European Union datasets (economics, agriculture)",
                "link": f"https://data.europa.eu/data/datasets?query={urllib.parse.quote(query)}",
                "source": "European Union",
                "student_friendly": True,
                "thumbnail": "https://data.europa.eu/favicon.ico"
            },
            {
                "title": "Awesome Public Datasets (GitHub)",
                "description": "Curated list of 100+ high-quality datasets (by topic)",
                "link": "https://github.com/awesomedata/awesome-public-datasets",
                "source": "GitHub",
                "student_friendly": True,
                "thumbnail": "https://github.githubassets.com/favicons/favicon.png"
            },
            {
                "title": "World Bank Open Data",
                "description": "Global development data (economics, climate, health)",
                "link": f"https://data.worldbank.org/?search={urllib.parse.quote(query)}",
                "source": "World Bank",
                "student_friendly": True,
                "thumbnail": "https://www.worldbank.org/content/dam/wbr/logo/wbg-favicon.png"
            },
            {
                "title": "WHO Health Data",
                "description": "Global health statistics (diseases, vaccinations)",
                "link": f"https://www.who.int/data/gho/search?indexCatalogue=ghoindex&searchQuery={urllib.parse.quote(query)}",
                "source": "World Health Org",
                "student_friendly": True,
                "thumbnail": "https://www.who.int/favicon.ico"
            },
            {
                "title": "Reddit Datasets",
                "description": "Community-shared datasets (r/datasets)",
                "link": f"https://www.reddit.com/r/datasets/search?q={urllib.parse.quote(query)}",
                "source": "Reddit",
                "student_friendly": True,
                "thumbnail": "https://www.redditstatic.com/favicon.ico"
            },
            {
                "title": "FiveThirtyEight Data",
                "description": "Sports, politics, and culture datasets",
                "link": "https://data.fivethirtyeight.com/",
                "source": "FiveThirtyEight",
                "student_friendly": True,
                "thumbnail": "https://fivethirtyeight.com/wp-content/themes/espn-fivethirtyeight/assets/images/favicon.png"
            },
        ]
        
        combined_datasets = datasets + essential_datasets
        cache['datasets'][query] = combined_datasets
        return combined_datasets
    
    except Exception as e:
        print(f"Error fetching datasets: {e}")
        return []
    
def lightweight_paraphrase(text):
    """Local-only paraphrasing using synonym replacement"""
    words = text.split()
    paraphrased = []
    
    for word in words:
        # Only replace nouns/verbs/adjectives (50% chance)
        if word.isalpha() and len(word) > 3 and random() > 0.5:
            synonyms = []
            for syn in wordnet.synsets(word):
                for lemma in syn.lemmas():
                    if lemma.name() != word:
                        synonyms.append(lemma.name().replace('_', ' '))
            if synonyms:
                paraphrased.append(choice(synonyms))
                continue
        paraphrased.append(word)
    
    return ' '.join(paraphrased)

@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")

@app.route("/search", methods=["POST"])
def search():
    try:
        query = request.form.get("query", "").strip()
        if not query:
            return render_template("index.html", error="Please enter a search query")
        
        papers = fetch_papers(query)
        code = fetch_code(query)
        ppts = fetch_ppts(query)
        datasets = fetch_datasets(query)
        
        return render_template("index.html", 
                             papers=papers, 
                             code=code, 
                             ppts=ppts,
                             datasets=datasets,
                             query=query)
    
    except Exception as e:
        print(f"Search error: {e}")
        return render_template("index.html", error="An error occurred during search")
    
@app.route('/paraphrase', methods=['POST'])
def paraphrase():
    text = request.json.get('text', '')[:500]  # Limit input size
    
    if not text.strip():
        return jsonify({"error": "Please enter text to paraphrase"})
    
    try:
        result = lightweight_paraphrase(text)
        return jsonify({
            "original": text,
            "paraphrased": result,
            "source": "Local NLTK"
        })
    except Exception as e:
        return jsonify({
            "original": text,
            "paraphrased": manual_rewrite(text),  # Fallback
            "source": "Basic Rewrite"
        })

def manual_rewrite(text):
    """Simple rule-based fallback"""
    replacements = [
        (" the ", " a "),
        (" is ", " can be "),
        (" are ", " were "),
        (" we ", " researchers "),
        (" our ", " the ")
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text

@app.route("/get_random_ideas", methods=["GET"])
def get_random_ideas():
    domain = request.args.get('domain', 'ai').lower()
    count = min(int(request.args.get('count', 10)), 20) 
    
    ideas = PROJECT_IDEAS.get(domain, PROJECT_IDEAS['ai'])
    
    random.shuffle(ideas)
    
    return jsonify({
        "ideas": ideas[:count],
        "domain": domain.upper()
    })

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
