////////////////////////////////////// Common functions //////////////////////////////////////

function get_slack_members() {

  // Set the member list limit in the Slack API request payload
  var payload = { "limit": 1000 };

  // Retrieve the Slack member list
  var raw_slack_members = make_slack_api_request("GET", SLACK_API_URL + "users.list", payload).text
    
  var sanitized_slack_members = []
  // For every Slack member
  for (var i = 0; i < raw_slack_members.members.length; i++) {
    // Ignore deleted users and bots
    if (raw_slack_members.members[i].deleted == false && raw_slack_members.members[i].is_bot == false) {
      // Set the user ID in the Slack API request payload
      payload = { "user": raw_slack_members.members[i].id };

      // Retrieve the Slack profile
      var member_profile = make_slack_api_request("GET", SLACK_API_URL + "users.profile.get", payload).text

      // Check if member is on PTO
      var pto = "No"
      if (member_profile.profile.status_text.toLowerCase().includes("vacation")) {
        pto = "Yes"
      }

      // Obtain GitHub username
      var github_username = ""
      if ("Xf01KX0SRLF3" in member_profile.profile.fields && "alt" in member_profile.profile.fields["Xf01KX0SRLF3"]) {
        github_username = member_profile.profile.fields["Xf01KX0SRLF3"].alt.replace(/ /g,'')
      }

      // Obtain country
      var country = ""
      if ("Xf04Q9EE6NA3" in member_profile.profile.fields && "value" in member_profile.profile.fields["Xf04Q9EE6NA3"]) {
        country = member_profile.profile.fields["Xf04Q9EE6NA3"].value
      }

      // Push combined information to sanitized list
      sanitized_slack_members.push({"Full name": member_profile.profile.real_name, "User ID": raw_slack_members.members[i].id, "GitHub username": github_username, "Country": country, "PTO": pto })
    }
  }

  return sanitized_slack_members
}

function get_github_teams() {

  var raw_github_teams = make_github_api_request("GET", GITHUB_STANDARD_API_URL + "orgs/wazuh/teams?per_page=100", null).text
  
  var sanitized_github_teams = []
  // For every GitHub team
  for (var i = 0; i < raw_github_teams.length; i++) {
    var github_team = raw_github_teams[i]

    // Filter the GitHub team based on the github_allowed_teams global variable
    if (github_allowed_teams.includes(github_team.name)) {
      sanitized_github_teams.push(github_team)
    }
  }

  return sanitized_github_teams
}

function get_github_team_members(github_team_slug) {

  var github_team_members = make_github_api_request("GET", GITHUB_STANDARD_API_URL + "orgs/wazuh/teams/" + github_team_slug + "/members?per_page=100", null).text

  return github_team_members
}

function get_github_community_project_issues() {

    var first_page_data =  `
    query { \
        node(id: "<replace_node_id>") { \
            ... on ProjectV2 { \
                items(first: 100, orderBy: {field: POSITION, direction: ASC}) { \
                    pageInfo { \
                        hasNextPage \
                        endCursor \
                    } \
                    nodes { \
                        id \
                        content { \
                            ... on Issue { \
                                id \
                                createdAt \
                                number \
                                assignees (first: 20) { nodes { login } } \
                            } \
                        } \
                        fieldValues(first: 20) { \
                            nodes { \
                                ... on ProjectV2ItemFieldIterationValue { \
                                    field { \
                                        ... on ProjectV2IterationField { \
                                            name \
                                        } \
                                    } \
                                    id \
                                    duration \
                                    startDate \
                                } \
                                ... on ProjectV2ItemFieldTextValue { \
                                    field { \
                                        ... on ProjectV2Field { \
                                            name \
                                        } \
                                    } \
                                    id \
                                    text \
                                } \
                                ... on ProjectV2ItemFieldNumberValue { \
                                    field { \
                                        ... on ProjectV2Field { \
                                            name \
                                        } \
                                    } \
                                    id \
                                    number \
                                } \
                                ... on ProjectV2ItemFieldSingleSelectValue { \
                                    field { \
                                        ... on ProjectV2SingleSelectField { \
                                            name \
                                        } \
                                    } \
                                    id \
                                    optionId \
                                    name \
                                } \
                            } \
                        } \
                    } \
                } \
            } \
        } \
    } \
    `

    var pagination_data =  `
    query { \
        node(id: "<replace_node_id>") { \
            ... on ProjectV2 { \
                items(first: 100, after: "<replace_after>", orderBy: {field: POSITION, direction: ASC}) { \
                    pageInfo { \
                        hasNextPage \
                        endCursor \
                    } \
                    nodes { \
                        id \
                        content { \
                            ... on Issue { \
                                id \
                                createdAt \
                                number \
                                assignees (first: 20) { nodes { login }} \
                            } \
                        } \
                        fieldValues(first: 20) { \
                            nodes { \
                                ... on ProjectV2ItemFieldIterationValue { \
                                    field { \
                                        ... on ProjectV2IterationField { \
                                            name \
                                        } \
                                    } \
                                    id \
                                    duration \
                                    startDate \
                                } \
                                ... on ProjectV2ItemFieldTextValue { \
                                    field { \
                                        ... on ProjectV2Field { \
                                            name \
                                        } \
                                    } \
                                    id \
                                    text \
                                } \
                                ... on ProjectV2ItemFieldNumberValue { \
                                    field { \
                                        ... on ProjectV2Field { \
                                            name \
                                        } \
                                    } \
                                    id \
                                    number \
                                } \
                                ... on ProjectV2ItemFieldSingleSelectValue { \
                                    field { \
                                        ... on ProjectV2SingleSelectField { \
                                            name \
                                        } \
                                    } \
                                    id \
                                    optionId \
                                    name \
                                } \
                            } \
                        } \
                    } \
                } \
            } \
        } \
    } \
    `

  var first_page_data = first_page_data.replace("<replace_node_id>", github_community_project_node_id)
  var pagination_data = pagination_data.replace("<replace_node_id>", github_community_project_node_id)

  // Request firt page
  var response = make_github_api_request("POST", GITHUB_GRAPHQL_API_URL, JSON.stringify({'query': first_page_data})).text
  
  // Initialize raw_github_issues list
  var raw_github_issues = response.data.node.items.nodes

  while (true) {
    // If there's a new data page
    if (response.data.node.items.pageInfo.hasNextPage) {
      var new_pagination_data = pagination_data.replace("<replace_after>", response.data.node.items.pageInfo.endCursor)

      // Request next page
      response = make_github_api_request("POST", GITHUB_GRAPHQL_API_URL, JSON.stringify({'query': new_pagination_data})).text

      // Concatenate page to raw_github_issues list
      raw_github_issues = raw_github_issues.concat(response.data.node.items.nodes)
    } else {
      break
    }
  }

  var sanitized_github_issues = []

  // For every issue in raw_github_issues
  for (var i = 0; i < raw_github_issues.length; i++) {

    var sanitized_github_issue = {}
    var raw_github_issue = raw_github_issues[i]

    if (raw_github_issue.content != null) {
      // Extract issue number and assignees from content data
      sanitized_github_issue["number"] = raw_github_issue.content.number
      sanitized_github_issue["assignees"] = raw_github_issue.content.assignees.nodes
      sanitized_github_issue["created_at"] = new Date(raw_github_issue.content.createdAt)

      // Extract title, status, team, time, year and week from project data
      for (var j = 0; j < raw_github_issue.fieldValues.nodes.length; j++) {
        var field = raw_github_issue.fieldValues.nodes[j]

        if ("field" in field) {
          if (field.field.name == "Title") {
            sanitized_github_issue["title"] = field.text
          }
          if (field.field.name == "Status") {
            sanitized_github_issue["status"] = field.name
          }
          if (field.field.name == "Team") {
            sanitized_github_issue["team"] = field.name
          }
          if (field.field.name.includes("Time")) {
            sanitized_github_issue["time"] = field.number
          }
          if (field.field.name == "Year") {
            sanitized_github_issue["year"] = field.name
          }
          if (field.field.name.includes("Week")) {
            sanitized_github_issue["week"] = field.text
          }
        }
      }

      // Push the sanitized issue into the sanitized_github_issues list
      sanitized_github_issues.push(sanitized_github_issue)
    }
  }

  return sanitized_github_issues
}

function get_slack_presence(user_id) {

  // Set the user ID in the Slack API request payload
  payload = { "user": user_id };

  var slack_presence = make_slack_api_request("GET", SLACK_API_URL + "users.getPresence", payload).text
  
  return slack_presence
}

function get_slack_dnd(user_id) {

  // Set the user ID in the Slack API request payload
  payload = { "user": user_id };

  var dnd = make_slack_api_request("GET", SLACK_API_URL + "dnd.info", payload).text
  
  return dnd
}

////////////////////////////////////// Main workflow //////////////////////////////////////

function summary_main () {

  // Get GitHub teams
  Logger.log("Get Github teams")
  var github_teams = get_github_teams()

  Logger.log("Get Slack members")
  // Get Slack members
  var slack_members = get_slack_members()

  // Get the Summary sheet
  var sheet = SpreadsheetApp.getActive().getSheetByName("Summary");

  Logger.log("Get GitHub community project issues")
  // Get GitHub community project issues
  var github_issues = get_github_community_project_issues()

  var community_data = []
  var total_assigned = 0
  var from_previous_weeks = 0

  // For every GitHub team
  for (var i = 0; i < github_teams.length; i++) {
    var github_team = github_teams[i]

    // Get its members
    var github_team_members = get_github_team_members(github_team.slug)

    // For every member
    for (var j = 0; j < github_team_members.length; j++) {

      var github_member = github_team_members[j]

      // Ignore the users inside the github_exclusion_list global variable
      if (!github_exclusion_list.includes(github_member.login )) {
        var ticket_count = 0

        // For every GitHub community project issue
        for (var l = 0; l < github_issues.length; l++) {
          var github_issue = github_issues[l]

          // If the week and year fields in the GitHub issue are the same than the current week and year
          if ("week" in github_issue && github_issue.week == current_week && "year" in github_issue && github_issue.year == current_year) {

            // For every assignee in the GitHub issue
            for (var k = 0; k < github_issue.assignees.length; k++) {
              // If the currently considered GitHub team member is assigned to the issue...
              if (github_member.login == github_issue.assignees[k].login) {
                // Increase the ticket count
                ticket_count = ticket_count + 1

                // Increase the total count
                total_assigned = total_assigned + 1

                // Count assigned issues created during previous weeks
                if (current_week != get_week_from_date(github_issue.created_at)) {
                  from_previous_weeks = from_previous_weeks + 1
                }
              }
            }
          }
        }

        var slack_user_id = ""
        var country = ""
        var within_working_hours = "No"
        var pto = ""
        var full_name = ""

        // For every Slack member
        for (var m = 0; m < slack_members.length; m++) {

          // If the currently considered GitHub member is the same that the one added to the Slack profile...
          if (slack_members[m]["GitHub username"] == github_member.login) {

            // Retrieve Slack presence status
            var slack_member_presence = get_slack_presence(slack_members[m]["User ID"])
            
            // If the Slack member is active
            if (slack_member_presence.presence == "active") {
              var current_time = new Date().getTime() / 1000

              // Retrieve the dnd status
              var slack_member_dnd = get_slack_dnd(slack_members[m]["User ID"])

              // If dnd is disabled, set within_working_hours to yes
              if (slack_member_dnd.dnd_enabled == false) {
                within_working_hours = "Yes"
              // If dnd is enabled but the current time is before dnd starts, set within_working_hours to yes
              } else if (current_time < slack_member_dnd.next_dnd_start_ts) {
                within_working_hours = "Yes"
              }
            }

            // Populate full_name, pto and country from Slack members data
            full_name = slack_members[m]["Full name"]
            slack_user_id = slack_members[m]["User ID"]
            pto = slack_members[m]["PTO"]
            country = slack_members[m]["Country"]
          }
        }

        // Add a priority field to later sort community data
        var priority = "c"
        if (pto == "No" && within_working_hours == "Yes") {
          if (ticket_count < 2) {
            priority = "a"
          } else {
            priority = "b"
          }
        }

        community_data.push([github_team.name, full_name, github_member.login, ticket_count, country, within_working_hours, pto, slack_user_id, priority])

      }
    }
  }

  // Sort community data based on priority
  community_data.sort(function(a, b){
    var priority_a = a[8]
    var priority_b = b[8]

    if (priority_a < priority_b) {
      return -1
    } else {
      return 1
    }
    return 0
  });

  // Clear the current contents of the sheet
  sheet.clear();

  // Add headers to the sheet
  sheet_week = ["Week " + current_week, "", "Total assigned", total_assigned, "", "From previous weeks", from_previous_weeks]
  sheet.appendRow(sheet_week);
  var range = sheet.getRange(1, 1, 1, sheet_week.length);
  range.setBorder(true, true, true, true, true, true)
  range.setFontWeight(fontWeight = "bold")
  range.setFontSize(size = 16)
  sheet_header = ["Team", "Full name", "GitHub username", "Ticket count", "Country", "Within working hours", "PTO", "Slack user ID"]
  sheet.appendRow(sheet_header);

  range = sheet.getRange(2, 1, 1, sheet_header.length);
  range.setBorder(true, true, true, true, true, true)
  range.setFontWeight(fontWeight = "bold")
  range.setFontSize(size = 12)

  // Write community summary information
  range = sheet.getRange(3, 1, community_data.length, community_data[0].length);
  range.setValues(community_data)
  range.setBorder(true, true, true, true, true, true)

  // Delete the priority column as it is no longer needed
  sheet.deleteColumn(community_data[0].length);

  // Add colors to rows based on ticket quota and availability criteria
  for (var i = 0; i < community_data.length; i++) {
    if (community_data[i][0] == "presales" || community_data[i][0] == "support" || community_data[i][0] == "proactive" || community_data[i][0] == "content") {
      if (community_data[i][6] == "No" && community_data[i][5] == "Yes" && community_data[i][3] < 3) {
        range = sheet.getRange(i + 3, 1, 1, sheet_header.length)
        range.setBackgroundRGB(0, 210, 0)
      } else if (community_data[i][6] == "No" && community_data[i][5] == "Yes" && community_data[i][3] >= 3) {
        range = sheet.getRange(i + 3, 1, 1, sheet_header.length)
        range.setBackgroundRGB(210, 210, 0)
      } else {
        range = sheet.getRange(i + 3, 1, 1, sheet_header.length)
        range.setBackgroundRGB(210, 0, 0)
      }

    } else {
      if (community_data[i][6] == "No" && community_data[i][5] == "Yes" && community_data[i][3] < 3) {
        range = sheet.getRange(i + 3, 1, 1, sheet_header.length)
        range.setBackgroundRGB(0, 210, 0)
      } else if (community_data[i][6] == "No" && community_data[i][5] == "Yes" && community_data[i][3] >= 3) {
        range = sheet.getRange(i + 3, 1, 1, sheet_header.length)
        range.setBackgroundRGB(210, 210, 0)
      } else {
        range = sheet.getRange(i + 3, 1, 1, sheet_header.length)
        range.setBackgroundRGB(210, 0, 0)
      }
    }
  }
}
