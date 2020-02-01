#!/usr/bin/env python3
import requests
import json
import subprocess
import params

from params import API_KEY, TARGET_ACCOUNT_NAME, INSERT_API_KEY

accountId = 0
# Helper function to run a graphQL query
def graphQL(query):
    r = requests.post('https://api.newrelic.com/graphql', json={"query": query}, headers={"API-Key": API_KEY})
    return r.json()['data']['actor']

# Function to save 0 instead of 'None' in dict before sending to New Relic
def dict_clean(items):
    result = {}
    for key, value in items:
        if value is None:
            value = '0'
        result[key] = value
    return result


# Retrieve all accounts and loop
accountData = graphQL("{ actor { accounts { id, name } } }")
for account in accountData['accounts']:
    # Retrieve account information
    accountId = account['id']
    accountName = account['name']
    if (accountName == TARGET_ACCOUNT_NAME):
        print("Retrieving data for %s" % accountName)

        resourceData = graphQL("{ actor { account(id: %s) { nrql(query: \"from Relationship select uniques(sourceEntityGuid) where sourceEntityType='APPLICATION'\") { results } } } }" % accountId)
        appGUIDs = resourceData['account']['nrql']['results'][0]["uniques.sourceEntityGuid"]

        entityNameDict = {}
        complexityResults = []
        highWatermarks = {}

        # For APPLICATION entities
        for appGUID in appGUIDs:
            entityComplexityDict = {}
            entityNameQuery = "{actor { account(id: "+str(accountId)+") { id } entity(guid:\""+appGUID+"\") { name } } }"
            entityNameData = graphQL(entityNameQuery)
            entityName = entityNameData['entity']['name']
            entityNameDict.update({appGUID: entityName})
            entityComplexityDict.update({"eventType": "complexity"})
            entityComplexityDict.update({"appName": entityName})

            # Count relationship types & put into relType (Note by adding the ...ApmAPplicationEntity clause INFRA relationships don't seem to be captured any more)
            appRelationshipsQueryString = "{actor {account(id: "+str(accountId)+") {id } entities(guids:\""+appGUID+"\") {relationships {source {entity {entityType guid name type } entityType } target {entity {entityType guid name type ... on ApmApplicationEntityOutline { language }} entityType } type } ... on ApmApplicationEntity { language } } } } "
            appRelationships = graphQL(appRelationshipsQueryString)   
            relType = {}
            depLanguage = {}
            for r in appRelationships.get("entities")[0].get("relationships"):
                rType = r.get("target").get("entity").get("entityType")
                relType[rType] = relType.get(rType, 0) +1
                targetLanguage = r.get("target").get("entity").get("language")
                depLanguage[targetLanguage] = depLanguage.get(targetLanguage,0) + 1

            # hwRelationshipsQueryString = "{actor {account(id: "+str(accountId)+") {id } entities(guids:\""+appGUID+"\") {relationships {source {entity {entityType guid name type } entityType } target {entity {entityType guid name type ... on InfrastructureHostEntityOutline { hostSummary { cpuUtilizationPercent diskUsedPercent memoryUsedPercent networkReceiveRate networkTransmitRate servicesCount } } entityType } type } } } } "
            # hwRelationships = graphQL(hwRelationshipsQueryString)   
            # hwRelType = {}
            # for r in hwRelationships.get("entities")[0].get("relationships"):
            #     rType = r.get("target").get("entity").get("entityType")
            #     hwRelType[rType] = hwRelType.get(rType, 0) +1
            #     print (rType)

            # update High Watermark (COULD ADD THIS)

            # Add complexity metrics to dict
            entityComplexityDict.update({"SW Dependencies": relType.get("APM_APPLICATION_ENTITY")})
            entityComplexityDict.update({"HW Dependencies": relType.get("INFRASTRUCTURE_HOST_ENTITY")})
            entityComplexityDict.update({"SW External Dependencies": relType.get("APM_EXTERNAL_SERVICE_ENTITY")})
            entityComplexityDict.update({"Database Dependencies": relType.get("APM_DATABASE_INSTANCE_ENTITY")})
            entityComplexityDict.update({"Browser Dependencies": relType.get("BROWSER_APPLICATION_ENTITY")})
            entityComplexityDict.update({"Num Languages": len(depLanguage)})

            # Take 1 off the language count to ignore 'None' which will exist
            entityComplexityDict.update({"Primary Language": appRelationships.get("entities")[0].get("language")})

            #Get Workload Counts & add to complexity dict
            numUniqueTransactionQuery = "{ actor { account(id: "+str(accountId)+") { id } entity(guid: \""+appGUID+"\") { nrdbQuery(nrql: \"SELECT uniquecount(name) FROM Transaction\") { results } } } }"
            numUniqueTransaction = graphQL(numUniqueTransactionQuery)
            entityComplexityDict.update({"Unique Transactions" : numUniqueTransaction.get("entity").get("nrdbQuery").get("results")[0].get("uniqueCount.name")})
            dict_clean (entityComplexityDict)

            # Get language
            # getAPMLanguageQuery = "{ actor { account(id: "+str(accountId)+") { id } entity(guid: \""+appGUID+"\") } }"
            # getAPMLanguage = graphQL(getAPMLanguageQuery)

            # Store complexity dict
            complexityResults.append(entityComplexityDict)

            # Progress Marker
            print ("Profiling "+entityName+"... done")
        
        # This is where I would load into NR
        with open('complexityOutput.json', 'w') as outfile:
            json.dump(complexityResults, outfile)

        bashcommand = "gzip -c complexityOutput.json | curl -X POST -H \"Content-Type: application/json\" -H \"X-Insert-Key: "+INSERT_API_KEY+"\" -H \"Content-Encoding: gzip\" https://insights-collector.newrelic.com/v1/accounts/"+str(accountId)+"/events --data-binary @-"
        print (bashcommand)
        subprocess.run(bashcommand.split()) #This not working for some reason



