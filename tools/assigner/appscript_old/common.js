////////////////////////////////////// Global variables //////////////////////////////////////

const GITHUB_STANDARD_API_URL = 'https://api.github.com/'
const GITHUB_GRAPHQL_API_URL = 'https://api.github.com/graphql'
const SLACK_API_URL = 'https://slack.com/api/'
const OPENAI_API_URL = 'https://api.openai.com/v1/chat/completions'

const github_community_project_node_id = "PVT_kwDOANHY9s4AKR_X"
const github_allowed_teams = ["devel-xdrsiem-agent", "devel-xdrsiem-server", "devel-xdrsiem-indexer", "devel-xdrsiem-dashboard", "devel-xdrsiem-qa", "devel-xdrsiem-devops", "devel-cti-threatintel", "devel-cti-development-div2", "devel-cloud-platform", "devel-cloud-cicd", "devel-cloud-ops", "devel-cloud-threatintel", "content", "ops-support", "ops-presales", "community", "ops-tam", "ops-trainings"]
const github_exclusion_list = ["wazuhci", "wazuh-cloud-cicd", "havidarou"]


const slack_community_channel_id = "GPAMKJHDM"
const slack_community_user_group_id = "S05FCSRVAF6"  
const slack_community_handle = "ops-tech-community-team"
const slack_community_channel_name = "c-community-tickets"

const current_week = get_current_week()
const current_year = get_current_year()

////////////////////////////////////// Common functions //////////////////////////////////////

function make_api_request(url, fetch_options) {
  try {
    var response = UrlFetchApp.fetch(url, fetch_options);

    if(response.getResponseCode() >= 200 && response.getResponseCode() <= 299) {
      return {"text": JSON.parse(response.getContentText()), "headers": response.getAllHeaders(), "code": response.getResponseCode()}
    } else {
      Logger.log("Bad response from " + url + " - " + response.getResponseCode() + " - " + JSON.parse(response.getContentText()))
    }
  } catch(error) {
    Logger.log("The API request performed against " + url + " failed: " + error)
    return {"text": "Error", "headers": "Error", "code": -1}
  }
}

function make_github_api_request(method, url, payload) {
  var github_api_fetch_options = {
    "method": method,
    "headers": {
      "Accept": "application/vnd.github+json",
      "Content-Type": "application/json",
      "Authorization": "Bearer " + PropertiesService.getScriptProperties().getProperty("github_token")
    }
  }

  if(payload != null) {
    github_api_fetch_options['payload'] = payload
  }

  return make_api_request(url, github_api_fetch_options)
}

function make_slack_api_request(method, url, payload, user = false) {
  var slack_api_fetch_options = {
    "method": method,
    "headers": {
      "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
      "Authorization": "Bearer " + PropertiesService.getScriptProperties().getProperty("slack_token")
    }
  }

  if (user == true) {
    slack_api_fetch_options.headers.Authorization = "Bearer " + PropertiesService.getScriptProperties().getProperty("slack_user_token")
  }

  if(payload != null) {
    slack_api_fetch_options['payload'] = payload
  }

  return make_api_request(url, slack_api_fetch_options)
}

function make_openai_api_request(method, url, payload) {
  var openai_api_fetch_options = {
    "method": method,
    "headers": {
      "Content-Type": "application/json",
      "Authorization": "Bearer " + PropertiesService.getScriptProperties().getProperty("openai_token")
    }
  }

  if(payload != null) {
    openai_api_fetch_options['payload'] = payload
  }

  return make_api_request(url, openai_api_fetch_options)
}

function get_current_year() {
  return new Date().getFullYear().toString()
}

function get_week_from_date(date) {
  var start_date = new Date(date.getFullYear(), 0, 1);
  var days = Math.ceil((date - start_date) / (24 * 60 * 60 * 1000));
  var week_number = Math.ceil(days / 7);

  return week_number.toString()
}

function get_current_week() {
  var date = new Date();
  var year = date.getFullYear();
  
  // Get the first day of the year
  var firstDay = new Date(year, 0, 1);
  
  // Find all the dates from the first day to current date
  var currentDate = new Date(firstDay);
  var weekCounter = 1;
  var firstWeekFound = false;
  
  while (currentDate <= date) {
    // If it's a working day (Monday-Friday)
    if (currentDate.getDay() !== 0 && currentDate.getDay() !== 6) {
      // If we hit a Monday and we've already found the first week
      if (currentDate.getDay() === 1 && firstWeekFound) {
        weekCounter++;
      }
      // Mark that we've found working days in the first week
      firstWeekFound = true;
    }
    currentDate.setDate(currentDate.getDate() + 1);
  }
  
  return weekCounter.toString();
}

