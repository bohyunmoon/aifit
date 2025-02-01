import React, { useState, useEffect } from 'react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { RadioGroup } from '@/components/ui/radio-group';
import { RadioGroupItem } from '@/components/ui/radio-group';
import { Label } from '@/components/ui/label';
import { FileJson } from 'lucide-react';

// Card subcomponents remain the same
const CardContent = ({ children, className = "" }) => (
  <div className={`p-6 pt-0 ${className}`}>{children}</div>
);

const CardHeader = ({ children }) => (
  <div className="p-6 pb-3">{children}</div>
);

const CardTitle = ({ children }) => (
  <h2 className="text-2xl font-semibold leading-none tracking-tight">{children}</h2>
);

const CardDescription = ({ children }) => (
  <p className="text-sm text-gray-500 dark:text-gray-400">{children}</p>
);

const CardFooter = ({ children, className = "" }) => (
  <div className={`p-6 pt-0 flex ${className}`}>{children}</div>
);

const JsonViewer = ({ data }) => (
  <div className="bg-gray-50 p-4 rounded-lg">
    <pre className="text-sm overflow-auto max-h-[600px]">
      {JSON.stringify(data, null, 2)}
    </pre>
  </div>
);

const calculateDuration = (exercises) => {
  let total = 0;
  exercises.forEach(exercise => {
    exercise.moves.forEach(move => {
      total += parseInt(move.duration);
    });
  });
  return total;
};

const WorkoutPlanner = () => {
  const [currentStep, setCurrentStep] = useState(0);
  const [answers, setAnswers] = useState({
    goal: '',
    fitnessLevel: '',
    equipment: '',
    timeCommitment: ''
  });
  const [showPlan, setShowPlan] = useState(false);
  const [workoutsData, setWorkoutsData] = useState(null);
  const [sessionDetails, setSessionDetails] = useState(null);
  const [workoutPlan, setWorkoutPlan] = useState({});
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('app');

  const questions = [
    {
      question: "What's your primary fitness goal?",
      options: ['Weight Loss', 'Muscle Building', 'Improved Flexibility', 'Cardiovascular Health'],
      field: 'goal'
    },
    {
      question: "What's your current fitness level?",
      options: ['Beginner', 'Intermediate', 'Advanced'],
      field: 'fitnessLevel'
    },
    {
      question: "What equipment do you have available?",
      options: ['Bodyweight Only', 'Dumbbells', 'Resistance Bands', 'Full Home Gym'],
      field: 'equipment'
    },
    {
      question: "How much time can you dedicate to working out each day?",
      options: ['20-25 minutes', '25-30 minutes', '30+ minutes'],
      field: 'timeCommitment'
    }
  ];

  const createWorkoutPlan = (sessionData) => {
    if (!sessionData || !sessionData.workouts) return {};
    
    const days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'];
    const dailyFocus = {
      monday: ['Cardiovascular Health', 'Core Strength'],
      tuesday: ['Weight Loss', 'Muscle Building'],
      wednesday: ['Flexibility', 'Core Strength'],
      thursday: ['Cardiovascular Health', 'Weight Loss'],
      friday: ['Muscle Building', 'Flexibility']
    };

    return days.reduce((plan, day) => {
      const exercises = [];
      let totalDuration = 0;
      const targetDuration = 20;
      const focusAreas = dailyFocus[day];

      // Find matching workouts
      const availableWorkouts = sessionData.workouts.slice();
      
      while (totalDuration < targetDuration && availableWorkouts.length > 0) {
        const workoutIndex = Math.floor(Math.random() * availableWorkouts.length);
        const workout = availableWorkouts[workoutIndex];
        
        if (workout.segments && workout.segments.length > 0) {
          const validSegment = workout.segments.find(s => s.exercises && s.exercises.length > 0);
          
          if (validSegment) {
            const exerciseBlock = {
              workout: workout.title,
              moves: validSegment.exercises.map(ex => ({
                name: ex.name,
                duration: ex.duration.split(' ')[0],
                timestamp: ex.timestamp || null
              }))
            };
            
            exercises.push(exerciseBlock);
            totalDuration += validSegment.exercises.reduce((sum, ex) => 
              sum + parseInt(ex.duration.split(' ')[0]), 0
            );
          }
        }
        
        availableWorkouts.splice(workoutIndex, 1);
      }

      plan[day] = {
        title: focusAreas.join(" & "),
        targetDuration: targetDuration,
        exercises: exercises
      };

      return plan;
    }, {});
  };

  useEffect(() => {
    const loadData = async () => {
      try {
        console.log('Starting to load files...');
        const [workoutsResponse, sessionsResponse] = await Promise.all([
          window.fs.readFile('workouts.json', { encoding: 'utf8' }),
          window.fs.readFile('session_details_v3.json', { encoding: 'utf8' })
        ]);

        const workouts = JSON.parse(workoutsResponse);
        console.log('Workouts parsed:', workouts?.fitness_videos?.length || 0, 'videos found');
        
        // Clean up the sessions response by removing the header text
        const cleanSessionsResponse = sessionsResponse.substring(
          sessionsResponse.indexOf('{'),
          sessionsResponse.lastIndexOf('}') + 1
        );
        const sessions = JSON.parse(cleanSessionsResponse);
        console.log('Sessions parsed:', sessions?.workouts?.length || 0, 'workouts found');
        
        setWorkoutsData(workouts);
        setSessionDetails(sessions);
        setIsLoading(false);
      } catch (err) {
        console.error('Error loading workout data:', err);
        setError(`Error loading workout data: ${err.message}`);
        setIsLoading(false);
      }
    };

    loadData();
  }, []);

  useEffect(() => {
    if (showPlan && sessionDetails && !isLoading) {
      const plan = createWorkoutPlan(sessionDetails);
      setWorkoutPlan(plan);
    }
  }, [showPlan, sessionDetails, isLoading]);

  const handleAnswer = (value) => {
    setAnswers(prev => ({
      ...prev,
      [questions[currentStep].field]: value
    }));

    if (currentStep < questions.length - 1) {
      setCurrentStep(prev => prev + 1);
    } else {
      setShowPlan(true);
    }
  };

  const resetQuiz = () => {
    setCurrentStep(0);
    setAnswers({
      goal: '',
      fitnessLevel: '',
      equipment: '',
      timeCommitment: ''
    });
    setShowPlan(false);
    setWorkoutPlan({});
  };

  const renderContent = () => {
    if (!showPlan) {
      return (
        <div className="space-y-4">
          <h3 className="text-lg font-medium">
            {questions[currentStep].question}
          </h3>
          <RadioGroup
            onValueChange={handleAnswer}
            className="space-y-3"
          >
            {questions[currentStep].options.map((option) => (
              <div key={option} className="flex items-center space-x-2">
                <RadioGroupItem value={option} id={option} />
                <Label htmlFor={option}>{option}</Label>
              </div>
            ))}
          </RadioGroup>
        </div>
      );
    }

    const plan = workoutPlan;
    if (!plan || Object.keys(plan).length === 0) {
      return (
        <div className="text-center py-4">
          <p>Generating your workout plan...</p>
        </div>
      );
    }

    return (
      <div className="space-y-8">
        <div className="bg-blue-50 p-4 rounded-lg">
          <h2 className="text-xl font-semibold mb-2">Your Personalized Workout Schedule</h2>
          <p className="text-sm text-gray-600">
            Fitness Level: {answers.fitnessLevel}<br />
            Equipment: {answers.equipment}<br />
            Daily Time Commitment: {answers.timeCommitment}
          </p>
        </div>

        {Object.entries(plan).map(([day, dayPlan]) => (
          <div key={day} className="border-l-4 border-blue-500 pl-4 pb-8">
            <div className="mb-4">
              <h4 className="text-xl font-bold mb-2">
                {day.charAt(0).toUpperCase() + day.slice(1)}
              </h4>
              <p className="text-lg text-gray-700 mb-1">{dayPlan.title}</p>
              <p className="text-sm text-gray-600">Duration: {calculateDuration(dayPlan.exercises)} minutes</p>
            </div>

            <div className="space-y-6">
              {dayPlan.exercises.map((exercise, index) => (
                <div key={index} className="ml-4">
                  <div className="flex items-center mb-2">
                    <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center mr-2">
                      {index + 1}
                    </div>
                    <h5 className="font-medium">{exercise.workout}</h5>
                  </div>
                  <div className="ml-10 grid grid-cols-1 md:grid-cols-2 gap-2">
                    {exercise.moves.map((move, moveIndex) => (
                      <div key={moveIndex} className="flex items-center justify-between">
                        <div className="flex items-center flex-1">
                          <div className="w-2 h-2 rounded-full bg-gray-400 mr-2"></div>
                          <span>{move.name}</span>
                        </div>
                        <div className="flex items-center space-x-2">
                          <span className="text-gray-600">{move.duration} min</span>
                          {move.timestamp && (
                            <a
                              href={move.timestamp}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-blue-500 hover:text-blue-700 hover:underline ml-2"
                            >
                              [video]
                            </a>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  };

  if (isLoading) {
    return (
      <div className="w-full max-w-4xl mx-auto">
        <Card>
          <CardContent>
            <div className="flex items-center justify-center">
              Loading workout data...
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (error) {
    return (
      <div className="w-full max-w-4xl mx-auto">
        <Card>
          <CardContent>
            <div className="text-red-500">{error}</div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="w-full max-w-4xl mx-auto">
      <div className="flex border-b mb-4">
        {[
          { id: 'app', label: 'Workout Planner' },
          { id: 'workouts', label: 'workouts.json' },
          { id: 'sessions', label: 'session_details_v3.json' }
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 ${
              activeTab === tab.id
                ? 'border-b-2 border-blue-500 text-blue-600'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'workouts' && (
        <Card>
          <CardHeader>
            <CardTitle>workouts.json</CardTitle>
            <CardDescription>Raw data from workouts.json file</CardDescription>
          </CardHeader>
          <CardContent>
            <JsonViewer data={workoutsData} />
          </CardContent>
        </Card>
      )}

      {activeTab === 'sessions' && (
        <Card>
          <CardHeader>
            <CardTitle>session_details_v3.json</CardTitle>
            <CardDescription>Raw data from session_details_v3.json file</CardDescription>
          </CardHeader>
          <CardContent>
            <JsonViewer data={sessionDetails} />
          </CardContent>
        </Card>
      )}

      {activeTab === 'app' && (
        <Card>
          <CardHeader>
            <CardTitle>Personalized Workout Planner</CardTitle>
            <CardDescription>
              {!showPlan ? "Answer a few questions to get your customized workout plan" : "Your Personalized Workout Plan"}
            </CardDescription>
            <div className="flex items-center space-x-2 mt-2 text-sm text-gray-500">
              <FileJson className="h-4 w-4" />
              <span>Data loaded from workouts.json and session_details_v2.json</span>
            </div>
          </CardHeader>
          <CardContent>
            {renderContent()}
          </CardContent>
          <CardFooter className="justify-end">
            {showPlan && (
              <Button onClick={resetQuiz} variant="outline" className="mr-2">
                Start Over
              </Button>
            )}
          </CardFooter>
        </Card>
      )}
    </div>
  );
};

export default WorkoutPlanner;