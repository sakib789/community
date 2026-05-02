////////////////////////////////////// Common functions //////////////////////////////////////

function get_github_community_unassigned_issues() {
  const nextPattern = /(?<=<)([\S]*)(?=>; rel="Next")/i;
  
  var response = make_github_api_request("GET", GITHUB_STANDARD_API_URL + "repos/wazuh/community/issues?per_page=100&assignee=none&sort=created&direction=asc", null)

  var link_header = response.headers.Link

  var remaining_pages = link_header && link_header.includes(`rel=\"next\"`)

  var unassigned_github_issues = response.text
  while (remaining_pages) {
    response = make_github_api_request("GET", link_header.match(nextPattern)[0], null)
    
    link_header = response.headers.Link

    remaining_pages = link_header && link_header.includes(`rel=\"next\"`)

    unassigned_github_issues = unassigned_github_issues.concat(response.text)
  }

  return unassigned_github_issues
}

function close_github_issue(issue_number) {

  const repo = "wazuh/community";
  const issue_url = GITHUB_STANDARD_API_URL + "repos/" + repo + "/issues/" + issue_number;

  // 1. Añadir el label "duplicate"
  make_github_api_request("POST", issue_url + "/labels", JSON.stringify(["Duplicate"]));

  // 2. Cerrar la issue con reason "not_planned"
  make_github_api_request("PATCH", issue_url, JSON.stringify({
    state: "closed",
    state_reason: "not_planned",
    assignees: []
  }));

}

function add_github_issue_to_project(issue_node_id) {
  var mutation = `
  mutation {
    addProjectV2ItemById(input: {projectId: "<replace_project_id>" contentId: "<replace_item_id>"}) {
      item {
        id
      }
    }
  }
  `
  mutation = mutation.replace("<replace_project_id>", github_community_project_node_id)
  mutation = mutation.replace("<replace_item_id>", issue_node_id)

  var response = make_github_api_request("POST", GITHUB_GRAPHQL_API_URL, JSON.stringify({'query': mutation})).text

  return response["data"]["addProjectV2ItemById"]["item"]["id"]
}

function get_github_project_configuration_fields() {
  var query = `
  {
    node(id: "<replace_project_id>") {
      ... on ProjectV2 {
        fields(first: 100) {
          nodes {
            ... on ProjectV2Field {
              name
              id
            }
            ... on ProjectV2IterationField {
              name
              id
            }
            ... on ProjectV2SingleSelectField {
              name
              id
              options {
                  id
                  name
              }
            }
          }
        }
      }
    }
  }
  `

  query = query.replace("<replace_project_id>", github_community_project_node_id)

  var response = make_github_api_request("POST", GITHUB_GRAPHQL_API_URL, JSON.stringify({'query': query})).text
  
  return response["data"]["node"]["fields"]["nodes"]
}

function populate_github_project_fields(issue_node_id, configuration_fields, team) {
  var week_mutation = `
  mutation {
    updateProjectV2ItemFieldValue(
      input: {
        projectId: "<replace_project_id>"
        itemId: "<replace_item_id>"
        fieldId: "<replace_field_id>"
        value: { 
          text: "<replace_value>"        
        }
      }
    ) {
      projectV2Item {
        id
      }
    }
  }
  `

  for (var i = 0; i < configuration_fields.length; i++) {
    var configuration_field = configuration_fields[i]

    if (configuration_field["name"] == "Week number") {
      week_mutation = week_mutation.replace("<replace_project_id>", github_community_project_node_id)
      week_mutation = week_mutation.replace("<replace_item_id>", issue_node_id)
      week_mutation = week_mutation.replace("<replace_field_id>", configuration_field["id"])
      week_mutation = week_mutation.replace("<replace_value>", current_week)

      make_github_api_request("POST", GITHUB_GRAPHQL_API_URL, JSON.stringify({'query': week_mutation}))
    }
  }

  var year_mutation = `
  mutation {
    updateProjectV2ItemFieldValue(
      input: {
        projectId: "<replace_project_id>"
        itemId: "<replace_item_id>"
        fieldId: "<replace_field_id>"
        value: { 
          singleSelectOptionId: "<replace_value>"        
        }
      }
    ) {
      projectV2Item {
        id
      }
    }
  }
  `

  for (var i = 0; i < configuration_fields.length; i++) {
    var configuration_field = configuration_fields[i]

    if (configuration_field["name"] == "Year") {
      for (var j = 0; j < configuration_field["options"].length; j++) {
        var option = configuration_field["options"][j]
        if (option["name"] == current_year) {
          year_mutation = year_mutation.replace("<replace_project_id>", github_community_project_node_id)
          year_mutation = year_mutation.replace("<replace_item_id>", issue_node_id)
          year_mutation = year_mutation.replace("<replace_field_id>", configuration_field["id"])
          year_mutation = year_mutation.replace("<replace_value>", option["id"])

          make_github_api_request("POST", GITHUB_GRAPHQL_API_URL, JSON.stringify({'query': year_mutation}))
        }
      }
    }
  }

  var team_mutation = `
  mutation {
    updateProjectV2ItemFieldValue(
      input: {
        projectId: "<replace_project_id>"
        itemId: "<replace_item_id>"
        fieldId: "<replace_field_id>"
        value: { 
          singleSelectOptionId: "<replace_value>"        
        }
      }
    ) {
      projectV2Item {
        id
      }
    }
  }
  `

  // Remove company branch name from team's name
  team = team.replace(/devel-/g, '')
  team = team.replace(/ops-/g, '')
  team = team.replace(/marketing-/g, '')

  for (var i = 0; i < configuration_fields.length; i++) {
    var configuration_field = configuration_fields[i]

    if (configuration_field["name"] == "Team") {
      for (var j = 0; j < configuration_field["options"].length; j++) {
        var option = configuration_field["options"][j]
        if (option["name"].toLowerCase() == team.toLowerCase()) {
          team_mutation = team_mutation.replace("<replace_project_id>", github_community_project_node_id)
          team_mutation = team_mutation.replace("<replace_item_id>", issue_node_id)
          team_mutation = team_mutation.replace("<replace_field_id>", configuration_field["id"])
          team_mutation = team_mutation.replace("<replace_value>", option["id"])

          make_github_api_request("POST", GITHUB_GRAPHQL_API_URL, JSON.stringify({'query': team_mutation}))
        }
      }
    }
  }
}

function assign_github_issue(issue_number, username) {

  make_github_api_request("GET", GITHUB_STANDARD_API_URL + "repos/wazuh/community/issues/" + issue_number + "/assignees", JSON.stringify({ "assignees": [ "wazuh-community", username ]}))
}

function get_available_team_members() {
  // Get the Summary sheet
  var sheet = SpreadsheetApp.getActive().getSheetByName("Summary");

  // Start from the third row to avoid the headers and fetch the first seven columns of the next 500 rows
  values = sheet.getRange(3, 1, 500, 8).getValues();

  var available_team_members = []

  for (var i = 0; i < values.length; i++) {
    row = values[i]

    if (row[0] == '') {
      break
    } else {
      // Only select team members with less than 3 tickets assigned, within working hours set to yes, and PTO set to no
      if (row[3] < 2 && row[5] == "Yes" && row[6] == "No") {
        available_team_members.push({"Team": row[0], "Full name": row[1], "GitHub username": row[2], "Slack user ID": row[7], "Ticket count": row[3]})
      } else {
        if(row[5] == "Yes" && row[6] == "No" && (row[0] == "community" || row[0] == "ops-support" || row[0] == "content" || row[0] == "ops-presales")) {
          available_team_members.push({"Team": row[0], "Full name": row[1], "GitHub username": row[2], "Slack user ID": row[7], "Ticket count": row[3]})
        }
      }
    }  
  }

  return available_team_members
}

function get_proposed_team_from_keywords(message) {

  var agent_team_keywords = ["FIM", "Wazuh agent", "remoted", "agentd", "inventory", "AWS", "Azure", "GCP"]
  var server_team_keywords = ["vulnerability", "analysisd", "Wazuh API", "Wazuh manager cluster"]
  var indexer_team_keywords = ["Wazuh indexer"]
  var dashboard_team_keywords = ["Wazuh dashboard"]
  var cloud_team_keywords = ["Wazuh Cloud service", "Wazuh indexer"]
  var devops_team_keywords = ["Docker", "Kubernetes", "Ansible", "Puppet"]
  var threat_intel_team_keywords = ["rules", "decoders", "SCA"]

  var proposed_team = "ops-support"

  for (var i = 0; i < agent_team_keywords.length; i++) {
    if (message.toLowerCase().includes(agent_team_keywords[i])) {
      proposed_team = "devel-xdrsiem-agent"
    }
  }

  for (var i = 0; i < server_team_keywords.length; i++) {
    if (message.toLowerCase().includes(server_team_keywords[i])) {
      proposed_team = "devel-xdrsiem-server"
    }
  }

  for (var i = 0; i < indexer_team_keywords.length; i++) {
    if (message.toLowerCase().includes(indexer_team_keywords[i])) {
      proposed_team = "devel-xdrsiem-indexer"
    }
  }

  for (var i = 0; i < dashboard_team_keywords.length; i++) {
    if (message.toLowerCase().includes(dashboard_team_keywords[i])) {
      proposed_team = "devel-xdrsiem-dashboard"
    }
  }

  for (var i = 0; i < cloud_team_keywords.length; i++) {
    if (message.toLowerCase().includes(cloud_team_keywords[i])) {
      proposed_team = "devel-cloud"
    }
  }

  for (var i = 0; i < devops_team_keywords.length; i++) {
    if (message.toLowerCase().includes(devops_team_keywords[i])) {
      proposed_team = "devel-xdrsiem-devops"
    }
  }

  for (var i = 0; i < threat_intel_team_keywords.length; i++) {
    if (message.toLowerCase().includes(threat_intel_team_keywords[i])) {
      proposed_team = "devel-cti-threatintel"
    }
  }

  return proposed_team
}

function get_openai_response(message) {
  var prompt = 
  `
  Only write a JSON object with two keys:
  - team: Decide which Teams is best suited to reply to Text.
  - response: Draft a technical response to Text considering Wazuh the main topic.

  Teams: 
  devel-xdrsiem-agent. Wazuh agent, FIM, remoted, agentd, inventory, AWS, Azure and GCP integrations.
  devel-xdrsiem-server. Vulnerability detector, analysisd, Wazuh API and Wazuh manager cluster.
  devel-xdrsiem-indexer. Wazuh indexer, Elasticsearch, OpenSearch.
  devel-xdrsiem-dashboard. Wazuh dashboard, Kibana, OpenSearch Dashboards.
  devel-xdrsiem-devops. Docker, Kubernetes, Ansible, Puppet deployments.
  devel-cloud. Wazuh Cloud service. Wazuh indexer cluster. Elasticsearch.
  devel-cti-threatintel. Rules. Decoders. SCA.

  Text:
  ` + message

  var response = make_openai_api_request("GET", OPENAI_API_URL, JSON.stringify({ "model": "gpt-4", "messages": [{ "role": "user", "content": prompt }], "temperature": 0, "max_tokens": 750 })).text
  
  var openai_response = ''
  if (response != "Error") {
    Logger.log ("    Valid OpenAI API response found. Analyzing...")

    // If we received a complete response, simply return it
    if (response["choices"][0]["finish_reason"] == "stop" || response["choices"][0]["finish_reason"] == "null" || response["choices"][0]["finish_reason"] == null) {
      // Check if the response is a JSON object
      try {
        openai_response  = JSON.parse(response["choices"][0]["message"]["content"])

      } catch (error) {
        Logger.log("    Error. Couldn't parse OpenAI response into a JSON object.\n" + error + ". Trying keyword based assignment...")

        var proposed_team = get_proposed_team_from_keywords(message)
        openai_response = {"team": proposed_team, "response": "Couldn't find viable OpenAI data."}
      }
    } else if (response["choices"][0]["finish_reason"] == "length") {
      Logger.log("    Warning. OpenAI response exceeded the max number of tokens. Trying keyword based assignment...")
      // TODO: Manually look for the team and partial response

      var proposed_team = get_proposed_team_from_keywords(message)
      openai_response = {"team": proposed_team, "response": "OpenAI response exceeded the max number of tokens."}
    } else {
      Logger.log("    Warning. Unknown OpenAI finish reason: " + response["choices"][0]["finish_reason"] + ". Trying keyword based assignment...")

      var proposed_team = get_proposed_team_from_keywords(message)
      openai_response = {"team": proposed_team, "response": "Couldn't find viable OpenAI data."}
    }
  } else {
      Logger.log("    Warning. Unknown OpenAI API error. Trying keyword based assignment.")

      var proposed_team = get_proposed_team_from_keywords(message)
      openai_response = {"team": proposed_team, "response": "Couldn't find viable OpenAI data."}
  }

  return openai_response
}

function get_random_int(min, max) {
    min = Math.ceil(min);
    max = Math.floor(max);
    return Math.floor(Math.random() * (max - min + 1)) + min;
}

function get_team_member(available_team_members, team) {
  var assignable_teams = ["ops-support", "ops-presales", "content"]

  if (team != "") {
    assignable_teams.push(team.toLowerCase())
  }

  // Compute a list assignable team members
  var assignable_team_members = []

  // For every available team member
  for (var i = 0; i < available_team_members.length; i++) {

    var available_team_member = available_team_members[i]

    // For every assignable team member
    for (var j = 0; j < assignable_teams.length; j++) {
      var assignable_team = assignable_teams[j]

      // If the team member's team is part of the assignable teams
      if (assignable_team == available_team_member["Team"]) {
        // Add the team member to the list
        assignable_team_members.push(available_team_member)
      }
    }
  }

  // There's no recommended Wazuh team member available, looking for any other team member
  if (assignable_team_members.length == 0) {

    Logger.log("    Warning.Couldn't find a recommended Wazuh team member. Expanding the search to all available team members...")

    assignable_team_members = []
    for (var i = 0; i < available_team_members.length; i++) {
      var available_team_member = available_team_members[i]

      for (var j = 0; j < github_allowed_teams.length; j++) {
        var github_allowed_team = github_allowed_teams[j]
        if (github_allowed_team == available_team_member["Team"]) {
          assignable_team_members.push(available_team_member)
        }
      }
    }
  }

  if (assignable_team_members.length == 0) {
    Logger.log("    Warning. No available Wazuh team member found.")
    return null
  } else {

    // Look for the team member with less tickets assigned
    var min_ticket_count = 1000
    for (var i = 0; i < available_team_members.length; i++) {
      var available_team_member = available_team_members[i]

      if (available_team_member["Ticket count"] < min_ticket_count) {
        min_ticket_count = available_team_member["Ticket count"]
      }
    }

    // Select a team member with the mininum ticket count
    for (var i = 0; i < available_team_members.length; i++) {
      var available_team_member = available_team_members[i]
      if (available_team_member["Ticket count"] == min_ticket_count) {
        
        return available_team_members.splice(i, 1)[0]
      }
    }
  }
}

function update_summary_sheet(github_username) {
  // Get the Summary sheet
  var sheet = SpreadsheetApp.getActive().getSheetByName("Summary");

  // Start from the third row to avoid the headers and fetch the first seven columns of the next 500 rows
  values = sheet.getRange(3, 1, 500, 7).getValues();

  for (var i = 0; i < values.length; i++) {
    row = values[i]

    if (row[2] == github_username) {
      var cell = sheet.getRange(i + 3, 4)
      cell.setValue(row[3] + 1)

      var row_range = sheet.getRange(i + 3, 1, 1, 8)
      if (row[3] + 1 >= 2) {
        row_range.setBackgroundRGB(210, 210, 0)
      } else {
        row_range.setBackgroundRGB(0, 210, 0)
      }
      break
    } 
  }
}

function send_github_issue_comment(issue_number, comment) {

  make_github_api_request("GET", GITHUB_STANDARD_API_URL + "repos/wazuh/community/issues/" + issue_number + "/comments", JSON.stringify({ "body": comment }))
}

function get_slack_message(issue_number) {

  // Retrieve Slack messages
  var raw_slack_messages = make_slack_api_request("GET", SLACK_API_URL + "search.messages", { "query": "in:#" + slack_community_channel_name + " from: <@U01UJ54NH43> Issue created \"#" + issue_number + "\"", "limit": 100 }, true).text

  if (raw_slack_messages.messages.matches.length == 0) {
    return null
  } else if (raw_slack_messages.messages.matches.length > 1) {
    Logger.log("    Warning. Multiple GitHub notifications found for " + issue_number)
  }

  return raw_slack_messages.messages.matches[0].ts
}

function send_slack_message(message, ts) {

  make_slack_api_request("POST", SLACK_API_URL + "chat.postMessage", { "channel": slack_community_channel_id, "text": message, "thread_ts": ts })
}

////////////////////////////////////// Main workflow //////////////////////////////////////

function assignment_main() {

  var week_day = new Date()

  // Only execute the assignment on week days
  if (week_day.getUTCDay() != 0 && week_day.getUTCDay() != 6) {
      
    // Get unassigned issues in the community GitHub project
    var unassigned_issues = get_github_community_unassigned_issues()

    // Obtain the GitHub community project configuration fields
    var configuration_fields = get_github_project_configuration_fields()

    if (unassigned_issues.length == 0) {
      Logger.log("No unassigned community GitHub issues found.")
    }

    var current_slack_user = ""
    var previous_slack_user = ""
    var previous_slack_issue_creation_time = new Date('2015-03-15T00:00:00Z')

    var current_discord_user = ""
    var previous_discord_user = ""
    var previous_discord_issue_creation_time = new Date('2015-03-15T00:00:00Z')

    // Get the list of available team members
    var available_team_members = get_available_team_members()

    // For every unassigend issue in the community GitHub project...
    for (var i = 0; i < unassigned_issues.length; i++) {
      var unassigned_issue = unassigned_issues[i]

      Logger.log("Considering GitHub issue number " + unassigned_issue.number + "...")

      // Add the GitHub issue to the GitHub community project
      var node_id = add_github_issue_to_project(unassigned_issue.node_id)

      var current_issue_creation_time = new Date(unassigned_issue.created_at)
      var current_time = new Date()

      var duplicate = false

      // Check if this is a Slack related issue created by wazuh-community, obtain the Slack user
      if (unassigned_issue.title.includes("slack") && unassigned_issue.user.login == "wazuh-community") {
        current_slack_user = unassigned_issue.title.split(' ')[0]

        // If the previous Slack issue was sent by the same user within 5 minutes, it will be considered a duplicated GitHub issue
        if (previous_slack_user == current_slack_user && previous_slack_issue_creation_time.getTime() + (5 * 60000) >= current_issue_creation_time.getTime()) {

          Logger.log("    Warning. Possible duplicated GitHub issue. Closing it.")
          duplicate = true

          // Close the GitHub issue
          close_github_issue(unassigned_issue.number)

          // Look for the Slack GitHub notification in the c-community-tickets channel
          var ts = get_slack_message(unassigned_issue.number.toString())

          // Send a comment to the GitHub issue
          send_github_issue_comment(unassigned_issue.number, "Possible duplicated GitHub issue. Closing it.")

          // Notify about the assignment with a a thread message in the Slack GitHub notification
          send_slack_message("Possible duplicated GitHub issue. Closing it. <!subteam^" + slack_community_user_group_id + "> please review and reopen if necessary.", ts)
        }

        // Update previous Slack user and creation time variables with the current values
        previous_slack_user = current_slack_user
        previous_slack_issue_creation_time = current_issue_creation_time
      }

      // Check if this is a Discord related issue created by wazuh-community, obtain the Discord user
      if (unassigned_issue.title.includes("discord") && unassigned_issue.user.login == "wazuh-community") {
        current_discord_user = unassigned_issue.title.split(' ')[0]

        // If the previous Discord issue was sent by the same user within 5 minutes, it will be considered a duplicated GitHub issue
        if (previous_discord_user == current_discord_user && previous_discord_issue_creation_time.getTime() + (5 * 60000) >= current_issue_creation_time.getTime()) {

          Logger.log("    Warning. Possible duplicated GitHub issue. Closing it.")
          duplicate = true

          // Close the GitHub issue
          close_github_issue(unassigned_issue.number)

          // Look for the Slack GitHub notification in the c-community-tickets channel
          var ts = get_slack_message(unassigned_issue.number.toString())

          // Send a comment to the GitHub issue
          send_github_issue_comment(unassigned_issue.number, "Possible duplicated GitHub issue. Closing it.")

          // Notify about the assignment with a a thread message in the Slack GitHub notification
          send_slack_message("Possible duplicated GitHub issue. Closing it. <!subteam^" + slack_community_user_group_id + "> please review and reopen if necessary.", ts)
        }

        // Update previous Discord user and creation time variables with the current values
        previous_discord_user = current_discord_user
        previous_discord_issue_creation_time = current_issue_creation_time
      }

      // Only consider unassigned issues created more than 5 minutes ago
      if (current_issue_creation_time.getTime() + (5 * 60000) <= current_time.getTime()) {

        // Only proceed if the GitHub issue is not considered a duplicate
        if (duplicate == false) {

          if (available_team_members.length > 0) {

            // Obtain a response and proposed team from OpenAI
            //var openai_data = get_openai_response(unassigned_issue.body)
            var proposed_team = get_proposed_team_from_keywords(unassigned_issue.body)

            // If there's a viable response...
            if (proposed_team != "") {

              Logger.log(available_team_members.length)
              // Obtain a team member to assign the issue to based on the available team members and the proposed team
              var team_member = get_team_member(available_team_members, proposed_team)

              // Check if a team member was selected
              if (team_member != null) {

                  // Look for the Slack GitHub notification in the c-community-tickets channel
                  var ts = get_slack_message(unassigned_issue.number.toString())

                  // Only proceed with the assignment if the Slack GitHub notification was found
                  if (ts != null) {

                    Logger.log("    Assigning " + team_member["GitHub username"] + ", " + team_member["Team"] + " to GitHub issue.")

                    // Assign the GitHub issue to the team member
                    assign_github_issue(unassigned_issue.number, team_member["GitHub username"])

                    // Update summary sheet
                    update_summary_sheet(team_member["GitHub username"])

                    // Populate the GitHub community project Week number, Team, and Year fields
                    populate_github_project_fields(node_id, configuration_fields, team_member["Team"])

                    // Send a comment to the GitHub issue with openai's proposed response
                    //var github_comment = `This is an automated response generated by OpenAI. **Use it only as a guideline** and make sure that you test it as it may be inaccurate:\r\n\r\n` + openai_data.response

                    //send_github_issue_comment(unassigned_issue.number, github_comment)

                    // Notify about the assignment with a a thread message in the Slack GitHub notification
                    send_slack_message("Assigned to <@" + team_member["Slack user ID"] + ">", ts)
                  } else {
                    Logger.log("    Error. No Slack notification was found for issue number " + unassigned_issue.number + ".")
                  }
                } else {
                  Logger.log("    Warning. No team members available.")
                }
            } else {
              Logger.log("    Error. No assignable team was found.")
            }
          } else {
            Logger.log("    Warning. No team members available.")
          }
        }
      } else {
        if (duplicate == false) {
          Logger.log("    The GitHub issue was created less than 5 min ago. Skipping assignment...")
        }
      }
    }
  }
}
